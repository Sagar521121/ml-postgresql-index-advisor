import json
import statistics
from typing import Any, Dict, List, Optional
from psycopg.errors import QueryCanceled
from src.database.connection import get_connection
from src.dataset.session_control import (
    apply_benchmark_session_settings,
    get_effective_session_settings,
)
from src.dataset.plan_stability import (
    generate_plan_hash,
    generate_plan_signature,
)


DEFAULT_REPETITIONS = 5
DEFAULT_WARMUPS = 2
DEFAULT_TIMEOUT_MS = 30000


def parse_explain_json(raw_result: Any) -> Dict[str, Any]:
    """
    Parse PostgreSQL EXPLAIN JSON output into a single dictionary representing
    the execution plan report.
    Handles raw JSON string, list of dicts, or already-parsed dict.
    Raises ValueError on malformed, missing, or empty data.
    """
    if raw_result is None:
        raise ValueError("EXPLAIN result is None.")

    if isinstance(raw_result, str):
        content = raw_result.strip()
        if not content:
            raise ValueError("EXPLAIN result is an empty string.")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Malformed EXPLAIN JSON string: {e}") from e
    else:
        parsed = raw_result

    if isinstance(parsed, list):
        if len(parsed) == 0:
            raise ValueError("EXPLAIN JSON returned an empty list.")
        parsed = parsed[0]

    if not isinstance(parsed, dict):
        raise ValueError(
            f"Expected dict from EXPLAIN JSON, got {type(parsed).__name__}."
        )

    return parsed


def extract_execution_time(plan: Any) -> float:
    """
    Extract the authoritative 'Execution Time' (in ms) from PostgreSQL EXPLAIN JSON.
    This is the primary runtime label.
    Raises ValueError if 'Execution Time' is missing, None, negative, or non-numeric.
    """
    if isinstance(plan, (str, list)):
        plan = parse_explain_json(plan)
    elif not isinstance(plan, dict):
        raise ValueError(f"Expected dict or JSON for plan, got {type(plan).__name__}.")

    if "Execution Time" not in plan:
        raise ValueError("EXPLAIN ANALYZE JSON did not return 'Execution Time'.")

    val = plan["Execution Time"]
    if val is None:
        raise ValueError("'Execution Time' field is None.")

    try:
        execution_time = float(val)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Malformed 'Execution Time' value: {val!r}") from e

    if execution_time < 0:
        raise ValueError(f"Invalid negative 'Execution Time': {execution_time}")

    return execution_time


def extract_planning_time(plan: Any) -> float:
    """
    Extract 'Planning Time' (in ms) from PostgreSQL EXPLAIN JSON.
    Stored separately and must NOT be included in the primary runtime label.
    Raises ValueError if 'Planning Time' is missing, None, negative, or non-numeric.
    """
    if isinstance(plan, (str, list)):
        plan = parse_explain_json(plan)
    elif not isinstance(plan, dict):
        raise ValueError(f"Expected dict or JSON for plan, got {type(plan).__name__}.")

    if "Planning Time" not in plan:
        raise ValueError("EXPLAIN JSON did not return 'Planning Time'.")

    val = plan["Planning Time"]
    if val is None:
        raise ValueError("'Planning Time' field is None.")

    try:
        planning_time = float(val)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Malformed 'Planning Time' value: {val!r}") from e

    if planning_time < 0:
        raise ValueError(f"Invalid negative 'Planning Time': {planning_time}")

    return planning_time


# Backward compatibility aliases
_parse_explain_json = parse_explain_json
_extract_execution_time = extract_execution_time
_extract_planning_time = extract_planning_time


def _run_explain_analyze(
    cur,
    query: str,
    timeout_ms: int,
) -> Dict[str, Any]:
    apply_benchmark_session_settings(cur)
    cur.execute(f"SET statement_timeout = {int(timeout_ms)}")

    cur.execute(
        f"""
        EXPLAIN (
            ANALYZE,
            TIMING OFF,
            FORMAT JSON
        )
        {query}
        """
    )

    result = cur.fetchone()[0]
    return parse_explain_json(result)


def benchmark_query(
    query: str,
    repetitions: int = DEFAULT_REPETITIONS,
    warmups: int = DEFAULT_WARMUPS,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    dbname: str = "job_imdb",
) -> Dict[str, Any]:
    """
    Measure the real execution time of a PostgreSQL query.
    Handles timeouts and cancellations cleanly without crashing the collector.

    Returns structured results distinguishing:
    - "SUCCESS": Completed all repetitions within timeout limit.
    - "TIMEOUT": Statement timed out (censored observation at timeout_ms).
    - "BENCHMARK_ERROR": Execution failed with a database error.
    """

    if repetitions <= 0:
        raise ValueError("repetitions must be greater than 0")

    if warmups < 0:
        raise ValueError("warmups cannot be negative")

    runtimes: List[float] = []
    planning_times: List[float] = []
    last_plan: Optional[Dict[str, Any]] = None

    with get_connection(dbname=dbname) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            session_settings = apply_benchmark_session_settings(cur)

            # Warm-up executions
            for _ in range(warmups):
                try:
                    _run_explain_analyze(
                        cur,
                        query,
                        timeout_ms,
                    )
                except QueryCanceled as e:
                    conn.rollback()
                    return {
                        "status": "TIMEOUT",
                        "timed_out": True,
                        "error_message": f"Warmup timed out: {e}",
                        "runtimes_ms": [],
                        "median_runtime_ms": None,
                        "min_runtime_ms": None,
                        "max_runtime_ms": None,
                        "mean_runtime_ms": None,
                        "planning_times_ms": [],
                        "planning_time_ms": None,
                        "median_planning_time_ms": None,
                        "min_planning_time_ms": None,
                        "max_planning_time_ms": None,
                        "mean_planning_time_ms": None,
                        "repetitions": repetitions,
                        "warmups": warmups,
                        "plan": None,
                        "plan_signature": None,
                        "plan_hash": None,
                        "session_settings": session_settings,
                        "jit": session_settings.get("jit", "off"),
                        "max_parallel_workers_per_gather": session_settings.get("max_parallel_workers_per_gather", 0),
                        "geqo": session_settings.get("geqo", "off"),
                    }
                except Exception as e:
                    conn.rollback()
                    return {
                        "status": "BENCHMARK_ERROR",
                        "timed_out": False,
                        "error_message": f"Warmup error: {e}",
                        "runtimes_ms": [],
                        "median_runtime_ms": None,
                        "min_runtime_ms": None,
                        "max_runtime_ms": None,
                        "mean_runtime_ms": None,
                        "planning_times_ms": [],
                        "planning_time_ms": None,
                        "median_planning_time_ms": None,
                        "min_planning_time_ms": None,
                        "max_planning_time_ms": None,
                        "mean_planning_time_ms": None,
                        "repetitions": repetitions,
                        "warmups": warmups,
                        "plan": None,
                        "plan_signature": None,
                        "plan_hash": None,
                        "session_settings": session_settings,
                        "jit": session_settings.get("jit", "off"),
                        "max_parallel_workers_per_gather": session_settings.get("max_parallel_workers_per_gather", 0),
                        "geqo": session_settings.get("geqo", "off"),
                    }

            # Measured executions
            for _ in range(repetitions):
                try:
                    plan = _run_explain_analyze(
                        cur,
                        query,
                        timeout_ms,
                    )
                    last_plan = plan

                    execution_time_ms = extract_execution_time(
                        plan
                    )
                    planning_time_ms = extract_planning_time(
                        plan
                    )

                    runtimes.append(execution_time_ms)
                    planning_times.append(planning_time_ms)
                except QueryCanceled as e:
                    conn.rollback()
                    return {
                        "status": "TIMEOUT",
                        "timed_out": True,
                        "error_message": f"Execution timed out: {e}",
                        "runtimes_ms": runtimes,
                        "median_runtime_ms": statistics.median(runtimes) if runtimes else None,
                        "min_runtime_ms": min(runtimes) if runtimes else None,
                        "max_runtime_ms": max(runtimes) if runtimes else None,
                        "mean_runtime_ms": statistics.mean(runtimes) if runtimes else None,
                        "planning_times_ms": planning_times,
                        "planning_time_ms": statistics.median(planning_times) if planning_times else None,
                        "median_planning_time_ms": statistics.median(planning_times) if planning_times else None,
                        "min_planning_time_ms": min(planning_times) if planning_times else None,
                        "max_planning_time_ms": max(planning_times) if planning_times else None,
                        "mean_planning_time_ms": statistics.mean(planning_times) if planning_times else None,
                        "repetitions": repetitions,
                        "warmups": warmups,
                        "plan": last_plan,
                        "plan_signature": generate_plan_signature(last_plan) if last_plan else None,
                        "plan_hash": generate_plan_hash(last_plan) if last_plan else None,
                        "session_settings": session_settings,
                        "jit": session_settings.get("jit", "off"),
                        "max_parallel_workers_per_gather": session_settings.get("max_parallel_workers_per_gather", 0),
                        "geqo": session_settings.get("geqo", "off"),
                    }
                except Exception as e:
                    conn.rollback()
                    return {
                        "status": "BENCHMARK_ERROR",
                        "timed_out": False,
                        "error_message": f"Execution error: {e}",
                        "runtimes_ms": runtimes,
                        "median_runtime_ms": None,
                        "min_runtime_ms": None,
                        "max_runtime_ms": None,
                        "mean_runtime_ms": None,
                        "planning_times_ms": planning_times,
                        "planning_time_ms": None,
                        "median_planning_time_ms": None,
                        "min_planning_time_ms": None,
                        "max_planning_time_ms": None,
                        "mean_planning_time_ms": None,
                        "repetitions": repetitions,
                        "warmups": warmups,
                        "plan": last_plan,
                        "plan_signature": generate_plan_signature(last_plan) if last_plan else None,
                        "plan_hash": generate_plan_hash(last_plan) if last_plan else None,
                        "session_settings": session_settings,
                        "jit": session_settings.get("jit", "off"),
                        "max_parallel_workers_per_gather": session_settings.get("max_parallel_workers_per_gather", 0),
                        "geqo": session_settings.get("geqo", "off"),
                    }

            median_runtime = statistics.median(runtimes)

            return {
                "status": "SUCCESS",
                "timed_out": False,
                "error_message": None,
                "runtimes_ms": runtimes,
                "median_runtime_ms": median_runtime,
                "min_runtime_ms": min(runtimes),
                "max_runtime_ms": max(runtimes),
                "mean_runtime_ms": statistics.mean(runtimes),
                "planning_times_ms": planning_times,
                "planning_time_ms": statistics.median(planning_times) if planning_times else None,
                "median_planning_time_ms": statistics.median(planning_times) if planning_times else None,
                "min_planning_time_ms": min(planning_times) if planning_times else None,
                "max_planning_time_ms": max(planning_times) if planning_times else None,
                "mean_planning_time_ms": statistics.mean(planning_times) if planning_times else None,
                "repetitions": repetitions,
                "warmups": warmups,
                "plan": last_plan,
                "plan_signature": generate_plan_signature(last_plan) if last_plan else None,
                "plan_hash": generate_plan_hash(last_plan) if last_plan else None,
                "session_settings": session_settings,
                "jit": session_settings.get("jit", "off"),
                "max_parallel_workers_per_gather": session_settings.get("max_parallel_workers_per_gather", 0),
                "geqo": session_settings.get("geqo", "off"),
            }
