"""
Decision #9 Part 1: A/A Control Benchmark.

Implements the A/A measurement protocol where the SAME query is executed under
the SAME database/index condition across separate measurement blocks to isolate
and quantify natural execution noise.

Locked Protocol:
- 2 warmups
- 5 measured executions
- EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON)
- Primary runtime: median of 5 measured Execution Times
- Planning Time stored separately
- Raw execution times preserved
- Noise formula:
    signed_log_ratio = log((T_A + 1.0) / (T_B + 1.0))
    abs_log_ratio = abs(log((T_A + 1.0) / (T_B + 1.0)))
  where T_A and T_B are block medians in milliseconds.
- Empirical dispersion statistics (median, p90, p95, max) as descriptive
  noise references, NOT confidence intervals.
"""

import math
import statistics
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import numpy as np

from src.dataset.plan_stability import (
    compare_plan_signatures,
    generate_plan_hash,
    generate_plan_signature,
)
from src.dataset.real_benchmark_executor import (
    DEFAULT_REPETITIONS,
    DEFAULT_TIMEOUT_MS,
    DEFAULT_WARMUPS,
    benchmark_query,
)

DEFAULT_AA_EPSILON_MS: float = 1.0


def calculate_aa_log_ratio(
    t_a: float,
    t_b: float,
    epsilon_ms: float = DEFAULT_AA_EPSILON_MS,
) -> Tuple[float, float]:
    """
    Calculate signed and absolute log-ratio between two measurement block medians:

        ratio = (t_a + epsilon_ms) / (t_b + epsilon_ms)
        signed = ln(ratio)
        absolute = |signed|

    Raises ValueError if t_a or t_b are negative or non-numeric.
    """
    if t_a is None or t_b is None:
        raise ValueError("Block runtimes t_a and t_b cannot be None.")

    try:
        t_a = float(t_a)
        t_b = float(t_b)
        eps = float(epsilon_ms)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Malformed runtime inputs: t_a={t_a!r}, t_b={t_b!r}") from e

    if t_a < 0 or t_b < 0:
        raise ValueError(f"Runtime cannot be negative: t_a={t_a}, t_b={t_b}")
    if eps <= 0:
        raise ValueError(f"epsilon_ms must be positive: {eps}")

    ratio = (t_a + eps) / (t_b + eps)
    signed_log_ratio = math.log(ratio)
    absolute_log_ratio = abs(signed_log_ratio)

    return (signed_log_ratio, absolute_log_ratio)


def calculate_dispersion_statistics(
    noise_values: Sequence[float],
) -> Dict[str, Any]:
    """
    Calculate empirical dispersion statistics from measured absolute log-ratios.

    IMPORTANT:
    These are descriptive empirical noise references, NOT confidence intervals
    or final noise thresholds.
    """
    if not noise_values:
        return {
            "count": 0,
            "median": None,
            "p90": None,
            "p95": None,
            "max": None,
            "min": None,
            "mean": None,
            "is_descriptive_reference_only": True,
            "statistical_meaning": "Descriptive empirical noise references, NOT confidence intervals.",
        }

    arr = np.asarray(noise_values, dtype=float)

    return {
        "count": int(len(arr)),
        "median": float(np.percentile(arr, 50)),
        "p90": float(np.percentile(arr, 90)),
        "p95": float(np.percentile(arr, 95)),
        "max": float(np.max(arr)),
        "min": float(np.min(arr)),
        "mean": float(np.mean(arr)),
        "is_descriptive_reference_only": True,
        "statistical_meaning": "Descriptive empirical noise references, NOT confidence intervals.",
    }


def run_aa_comparison(
    query: str,
    query_id: str,
    repetitions: int = DEFAULT_REPETITIONS,
    warmups: int = DEFAULT_WARMUPS,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    dbname: str = "job_imdb",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Run an authoritative A/A benchmark comparison:
    Execute query in Block A, then in Block B under identical conditions.
    Both blocks strictly follow the locked repetition protocol (2 warmups, 5 measured).
    """
    # Block A
    block_a_res = benchmark_query(
        query=query,
        repetitions=repetitions,
        warmups=warmups,
        timeout_ms=timeout_ms,
        dbname=dbname,
    )

    # Block B
    block_b_res = benchmark_query(
        query=query,
        repetitions=repetitions,
        warmups=warmups,
        timeout_ms=timeout_ms,
        dbname=dbname,
    )

    t_a = block_a_res.get("median_runtime_ms")
    t_b = block_b_res.get("median_runtime_ms")

    # Determine overall status
    if block_a_res["status"] == "BENCHMARK_ERROR" or block_b_res["status"] == "BENCHMARK_ERROR":
        status = "BENCHMARK_ERROR"
        error_message = (
            block_a_res.get("error_message") or block_b_res.get("error_message")
        )
    elif block_a_res["status"] == "TIMEOUT" or block_b_res["status"] == "TIMEOUT":
        status = "TIMEOUT"
        error_message = (
            block_a_res.get("error_message") or block_b_res.get("error_message")
        )
    else:
        status = "SUCCESS"
        error_message = None

    # Calculate noise log ratios
    if status == "SUCCESS" and t_a is not None and t_b is not None:
        signed_log_ratio, abs_log_ratio = calculate_aa_log_ratio(
            t_a=t_a,
            t_b=t_b,
            epsilon_ms=DEFAULT_AA_EPSILON_MS,
        )
    else:
        signed_log_ratio = None
        abs_log_ratio = None

    # Compare structural plans
    plan_a = block_a_res.get("plan")
    plan_b = block_b_res.get("plan")

    sig_a = block_a_res.get("plan_signature") or generate_plan_signature(plan_a)
    sig_b = block_b_res.get("plan_signature") or generate_plan_signature(plan_b)

    hash_a = block_a_res.get("plan_hash") or generate_plan_hash(plan_a)
    hash_b = block_b_res.get("plan_hash") or generate_plan_hash(plan_b)

    plan_comparison = compare_plan_signatures(plan_a, plan_b)
    plan_changed = plan_comparison["plan_changed"]
    plan_change_event = plan_comparison["plan_change_event"]

    return {
        "query_id": query_id,
        "control_type": "aa_control",
        "status": status,
        "error_message": error_message,
        "epsilon_ms": DEFAULT_AA_EPSILON_MS,
        "t_a": t_a,
        "t_b": t_b,
        "signed_log_ratio": signed_log_ratio,
        "absolute_log_ratio": abs_log_ratio,
        "block_a": {
            "status": block_a_res["status"],
            "timed_out": block_a_res["timed_out"],
            "runtimes_ms": block_a_res["runtimes_ms"],
            "median_runtime_ms": t_a,
            "min_runtime_ms": block_a_res.get("min_runtime_ms"),
            "max_runtime_ms": block_a_res.get("max_runtime_ms"),
            "mean_runtime_ms": block_a_res.get("mean_runtime_ms"),
            "planning_times_ms": block_a_res["planning_times_ms"],
            "planning_time_ms": block_a_res.get("planning_time_ms"),
            "median_planning_time_ms": block_a_res.get("median_planning_time_ms"),
            "repetitions": block_a_res["repetitions"],
            "warmups": block_a_res["warmups"],
            "plan": plan_a,
            "plan_signature": sig_a,
            "plan_hash": hash_a,
        },
        "block_b": {
            "status": block_b_res["status"],
            "timed_out": block_b_res["timed_out"],
            "runtimes_ms": block_b_res["runtimes_ms"],
            "median_runtime_ms": t_b,
            "min_runtime_ms": block_b_res.get("min_runtime_ms"),
            "max_runtime_ms": block_b_res.get("max_runtime_ms"),
            "mean_runtime_ms": block_b_res.get("mean_runtime_ms"),
            "planning_times_ms": block_b_res["planning_times_ms"],
            "planning_time_ms": block_b_res.get("planning_time_ms"),
            "median_planning_time_ms": block_b_res.get("median_planning_time_ms"),
            "repetitions": block_b_res["repetitions"],
            "warmups": block_b_res["warmups"],
            "plan": plan_b,
            "plan_signature": sig_b,
            "plan_hash": hash_b,
        },
        "plan_signature_a": sig_a,
        "plan_signature_b": sig_b,
        "plan_hash_a": hash_a,
        "plan_hash_b": hash_b,
        "plan_changed": plan_changed,
        "plan_change_event": plan_change_event,
        "metadata": metadata or {},
    }


def run_aa_suite(
    queries: Union[Dict[str, str], Sequence[Tuple[str, str]]],
    repetitions: int = DEFAULT_REPETITIONS,
    warmups: int = DEFAULT_WARMUPS,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    dbname: str = "job_imdb",
) -> Dict[str, Any]:
    """
    Run A/A comparisons across multiple queries.
    Aggregates observations and computes empirical dispersion statistics.
    """
    items = queries.items() if isinstance(queries, dict) else queries
    observations: List[Dict[str, Any]] = []

    for qid, qsql in items:
        obs = run_aa_comparison(
            query=qsql,
            query_id=qid,
            repetitions=repetitions,
            warmups=warmups,
            timeout_ms=timeout_ms,
            dbname=dbname,
        )
        observations.append(obs)

    successful = [o for o in observations if o["status"] == "SUCCESS" and o["absolute_log_ratio"] is not None]
    abs_ratios = [o["absolute_log_ratio"] for o in successful]

    dispersion = calculate_dispersion_statistics(abs_ratios)
    plan_changes = [o for o in observations if o["plan_change_event"]]

    return {
        "observations": observations,
        "successful_count": len(successful),
        "total_count": len(observations),
        "dispersion_statistics": dispersion,
        "plan_change_events": plan_changes,
    }
