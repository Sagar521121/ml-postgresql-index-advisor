import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from src.database.connection import get_connection
from src.dataset.session_control import apply_benchmark_session_settings
from src.dataset.real_benchmark_executor import (
    DEFAULT_REPETITIONS,
    DEFAULT_TIMEOUT_MS,
    DEFAULT_WARMUPS,
    benchmark_query,
)
from src.dataset.plan_stability import (
    generate_plan_hash,
    generate_plan_signature,
)


def _extract_plan_cost(plan: Optional[Dict[str, Any]]) -> Optional[float]:
    """Extract Total Cost from plan root if available."""
    if not plan:
        return None
    root = plan.get("Plan", plan)
    if isinstance(root, list) and len(root) > 0:
        root = root[0]
    if isinstance(root, dict):
        try:
            return float(root.get("Total Cost", 0.0))
        except (ValueError, TypeError):
            return None
    return None


def measure_baseline_block(
    query: str,
    query_id: Optional[str] = None,
    sequence_number: int = 1,
    repetitions: int = DEFAULT_REPETITIONS,
    warmups: int = DEFAULT_WARMUPS,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    dbname: str = "job_imdb",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Measure an authoritative baseline block for a query following the locked protocol:
    - Exactly 2 warmups
    - Exactly 5 measured executions
    - EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON)
    - Primary runtime = median of 5 measured Execution Times (T_baseline)
    - Planning Time stored separately
    - Complete JSON plan preserved
    - Unique baseline_block_id, sequence_number, and created_at timestamp
    """
    clean_query_id = query_id or "query"
    uid = uuid.uuid4().hex[:8]
    created_at = datetime.now(timezone.utc).isoformat()
    baseline_block_id = f"base_{clean_query_id}_seq{sequence_number}_{uid}"

    # Execute benchmark according to locked repetition protocol
    benchmark_result = benchmark_query(
        query=query,
        repetitions=repetitions,
        warmups=warmups,
        timeout_ms=timeout_ms,
        dbname=dbname,
    )

    effective_plan = benchmark_result.get("plan")
    baseline_cost = _extract_plan_cost(effective_plan)

    # If plan wasn't captured (e.g. timeout during execution), fallback to static EXPLAIN (FORMAT JSON)
    if baseline_cost is None:
        try:
            with get_connection(dbname=dbname) as conn:
                conn.autocommit = True
                with conn.cursor() as cur:
                    apply_benchmark_session_settings(cur)
                    cur.execute(f"EXPLAIN (FORMAT JSON) {query}")
                    res = cur.fetchone()[0]
                    effective_plan = res[0] if isinstance(res, list) and len(res) > 0 else res
                    baseline_cost = _extract_plan_cost(effective_plan)
        except Exception:
            pass

    median_runtime = benchmark_result.get("median_runtime_ms")

    return {
        "baseline_block_id": baseline_block_id,
        "query_id": query_id,
        "sequence_number": sequence_number,
        "created_at": created_at,
        "status": benchmark_result["status"],
        "timed_out": benchmark_result["timed_out"],
        "error_message": benchmark_result["error_message"],
        "warmups": benchmark_result["warmups"],
        "repetitions": benchmark_result["repetitions"],
        # Authoritative Execution Times (primary runtime metric)
        "runtimes_ms": benchmark_result["runtimes_ms"],
        "median_runtime_ms": median_runtime,
        "T_baseline": median_runtime,  # Explicit definition of T_baseline
        "min_runtime_ms": benchmark_result["min_runtime_ms"],
        "max_runtime_ms": benchmark_result["max_runtime_ms"],
        "mean_runtime_ms": benchmark_result["mean_runtime_ms"],
        # Planning Times (stored separately)
        "planning_times_ms": benchmark_result["planning_times_ms"],
        "planning_time_ms": benchmark_result["planning_time_ms"],
        "median_planning_time_ms": benchmark_result["median_planning_time_ms"],
        "min_planning_time_ms": benchmark_result["min_planning_time_ms"],
        "max_planning_time_ms": benchmark_result["max_planning_time_ms"],
        "mean_planning_time_ms": benchmark_result["mean_planning_time_ms"],
        # Plan structure & cost
        "cost": baseline_cost,
        "plan": effective_plan,
        "plan_signature": benchmark_result.get("plan_signature") or (generate_plan_signature(effective_plan) if effective_plan else None),
        "plan_hash": benchmark_result.get("plan_hash") or (generate_plan_hash(effective_plan) if effective_plan else None),
        "metadata": metadata or {},
        # Decision #8: JIT, GEQO, and Parallelism Control
        "session_settings": benchmark_result.get("session_settings", {"jit": "off", "max_parallel_workers_per_gather": 0, "geqo": "off"}),
        "jit": benchmark_result.get("jit", "off"),
        "max_parallel_workers_per_gather": benchmark_result.get("max_parallel_workers_per_gather", 0),
        "geqo": benchmark_result.get("geqo", "off"),
    }


class BaselineManager:
    """
    Manages baseline measurement blocks, drift control, and candidate linkage.

    Guarantees:
    - Never overwrites old baselines: maintains an immutable history of all baseline blocks per query.
    - Provides explicit API to request a fresh baseline block at any point in the campaign.
    - Preserves exact linkage between candidate benchmarks and the baseline block used.
    """

    def __init__(self, dbname: str = "job_imdb"):
        self.dbname = dbname
        # query_id -> list of baseline blocks in chronological order
        self._history: Dict[str, List[Dict[str, Any]]] = {}
        # baseline_block_id -> baseline block dict
        self._blocks_by_id: Dict[str, Dict[str, Any]] = {}
        # baseline_block_id -> list of candidate names/identifiers measured against it
        self._candidates_by_baseline: Dict[str, List[str]] = {}

    def get_or_create_baseline(
        self,
        query: str,
        query_id: str,
        repetitions: int = DEFAULT_REPETITIONS,
        warmups: int = DEFAULT_WARMUPS,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> Dict[str, Any]:
        """
        Return the active baseline for query_id. If none exists yet, measure sequence #1.
        """
        if query_id in self._history and len(self._history[query_id]) > 0:
            return self._history[query_id][-1]

        return self.request_fresh_baseline(
            query=query,
            query_id=query_id,
            reason="initial_baseline",
            repetitions=repetitions,
            warmups=warmups,
            timeout_ms=timeout_ms,
        )

    def request_fresh_baseline(
        self,
        query: str,
        query_id: str,
        reason: Optional[str] = None,
        repetitions: int = DEFAULT_REPETITIONS,
        warmups: int = DEFAULT_WARMUPS,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> Dict[str, Any]:
        """
        Measure a fresh baseline block for query_id.
        Does NOT overwrite previous baselines; appends to the query's history with an incremented sequence number.
        """
        history = self._history.setdefault(query_id, [])
        next_seq = len(history) + 1

        prev_id = history[-1]["baseline_block_id"] if history else None
        meta = {
            "reason": reason or ("initial_baseline" if next_seq == 1 else "drift_refresh"),
            "previous_block_id": prev_id,
        }

        block = measure_baseline_block(
            query=query,
            query_id=query_id,
            sequence_number=next_seq,
            repetitions=repetitions,
            warmups=warmups,
            timeout_ms=timeout_ms,
            dbname=self.dbname,
            metadata=meta,
        )

        history.append(block)
        self._blocks_by_id[block["baseline_block_id"]] = block
        self._candidates_by_baseline.setdefault(block["baseline_block_id"], [])
        return block

    def link_candidate_to_baseline(
        self,
        baseline_block_id: str,
        candidate_identifier: str,
    ) -> None:
        """Record that a candidate was measured against a specific baseline block."""
        if baseline_block_id not in self._blocks_by_id:
            # Register unknown baseline ad-hoc so linkage is not lost
            self._blocks_by_id[baseline_block_id] = {"baseline_block_id": baseline_block_id}
        self._candidates_by_baseline.setdefault(baseline_block_id, []).append(candidate_identifier)

    def get_candidates_for_baseline(self, baseline_block_id: str) -> List[str]:
        """Return all candidates measured against a given baseline block ID."""
        return list(self._candidates_by_baseline.get(baseline_block_id, []))

    def get_baseline_history(self, query_id: str) -> List[Dict[str, Any]]:
        """Return all historical baseline blocks measured for query_id."""
        return list(self._history.get(query_id, []))

    def get_baseline_by_id(self, baseline_block_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a baseline block by its unique ID."""
        return self._blocks_by_id.get(baseline_block_id)

    def get_active_baseline(self, query_id: str) -> Optional[Dict[str, Any]]:
        """Return the most recent active baseline block for query_id."""
        history = self._history.get(query_id)
        return history[-1] if history else None
