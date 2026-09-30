from typing import Any, Dict, List, Optional, Tuple, Union
from src.database.connection import get_connection
from src.dataset.session_control import apply_benchmark_session_settings
from src.dataset.real_benchmark_executor import (
    DEFAULT_REPETITIONS,
    DEFAULT_TIMEOUT_MS,
    DEFAULT_WARMUPS,
    benchmark_query,
)
from src.dataset.baseline_manager import (
    BaselineManager,
    measure_baseline_block,
)
from src.dataset.timeout_policy import (
    DEFAULT_EPSILON_MS,
    DEFAULT_MIN_TIMEOUT_SECONDS,
    DEFAULT_TIMEOUT_MULTIPLIER,
    calculate_dynamic_timeout_limit,
    compute_speedup_target,
    compute_timeout_target,
)
from src.dataset.plan_stability import (
    compare_plan_signatures,
    generate_plan_hash,
    generate_plan_signature,
)

EXPERIMENTAL_INDEX_PREFIX = "exp_idx_"


def _collect_used_indexes(plan_node: dict) -> List[str]:
    """Recursively extract all index names referenced in the plan tree."""
    used_indexes = []

    def walk(node):
        if not isinstance(node, dict):
            return

        index_name = node.get("Index Name")
        if index_name:
            used_indexes.append(index_name)

        for child in node.get("Plans", []):
            walk(child)

    walk(plan_node)
    return used_indexes


def _get_plan_signature(node: dict) -> Tuple:
    """
    Build a recursive structural signature of the execution plan tree.
    Includes Node Type, Relation Name, Index Name, Join Type, and tree topology.
    """
    if not isinstance(node, dict):
        return ()

    sig = (
        node.get("Node Type"),
        node.get("Relation Name"),
        node.get("Index Name"),
        node.get("Join Type"),
        node.get("Parent Relationship"),
    )

    children_sig = tuple(_get_plan_signature(ch) for ch in node.get("Plans", []))
    return (sig, children_sig)


def _is_plan_structurally_identical(
    baseline_root: dict,
    real_root: dict,
) -> bool:
    """Check if two plan trees share identical structural topology and operators."""
    return _get_plan_signature(baseline_root) == _get_plan_signature(real_root)


def make_experimental_index_name(
    table: str,
    columns: Union[List[str], Tuple[str, ...]],
) -> str:
    """Generate a deterministic experimental index name with the required prefix."""
    cols_str = "_".join(columns)
    return f"{EXPERIMENTAL_INDEX_PREFIX}{table}_{cols_str}"


def build_create_index_sql(
    index_name: str,
    table: str,
    columns: Union[List[str], Tuple[str, ...]],
) -> str:
    """Build standard CREATE INDEX SQL with explicit index name."""
    cols_sql = ", ".join(f'"{c}"' for c in columns)
    return f'CREATE INDEX "{index_name}" ON "{table}" ({cols_sql})'


def drop_experimental_index(
    index_name: str,
    dbname: str = "job_imdb",
) -> bool:
    """
    Drop an experimental index using a dedicated autocommit connection.
    This guarantees that the DROP statement succeeds even if a prior benchmark connection
    entered an aborted transaction state.
    """
    with get_connection(dbname=dbname) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'DROP INDEX IF EXISTS "{index_name}"')
    return True


def verify_index_absent(
    index_name: str,
    dbname: str = "job_imdb",
) -> bool:
    """
    Verify through PostgreSQL system catalogs that the specified index does not exist.
    Returns True if the index is confirmed absent, False if it still exists.
    """
    query = """
        SELECT 1
        FROM pg_index ix
        JOIN pg_class i ON i.oid = ix.indexrelid
        JOIN pg_namespace n ON n.oid = i.relnamespace
        WHERE n.nspname = 'public'
          AND i.relname = %s;
    """
    with get_connection(dbname=dbname) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(query, (index_name,))
            return cur.fetchone() is None


def cleanup_leftover_experimental_indexes(
    dbname: str = "job_imdb",
    prefix: str = EXPERIMENTAL_INDEX_PREFIX,
) -> List[str]:
    """
    Startup and maintenance sweep: find and remove all leftover experimental indexes
    matching the prefix in the public schema using a dedicated autocommit connection.
    """
    find_query = """
        SELECT i.relname
        FROM pg_index ix
        JOIN pg_class i ON i.oid = ix.indexrelid
        JOIN pg_namespace n ON n.oid = i.relnamespace
        WHERE n.nspname = 'public'
          AND i.relname LIKE %s;
    """
    dropped = []

    with get_connection(dbname=dbname) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(find_query, (f"{prefix}%",))
            rows = cur.fetchall()
            index_names = [r[0] for r in rows]

            for name in index_names:
                cur.execute(f'DROP INDEX IF EXISTS "{name}"')
                dropped.append(name)

    return dropped


def benchmark_with_real_index(
    query: str,
    index_sql: str,
    index_name: str,
    table_name: Optional[str] = None,
    repetitions: int = DEFAULT_REPETITIONS,
    warmups: int = DEFAULT_WARMUPS,
    timeout_ms: int = 30000,
    dbname: str = "job_imdb",
    run_analyze: bool = False,
    baseline_plan: Optional[Dict[str, Any]] = None,
    baseline_benchmark: Optional[Dict[str, Any]] = None,
    query_id: Optional[str] = None,
    baseline_manager: Optional[Any] = None,
    statistics_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create a real PostgreSQL index, benchmark the query, inspect the real execution plan,
    and always remove the index afterward.

    Safety and Robustness Guarantees:
    - Enforces the 'exp_idx_' naming convention.
    - Captures baseline execution runtimes and plan prior to CREATE INDEX (or accepts pre-computed baseline).
    - Cleans up via a dedicated autocommit connection, immune to aborted transaction states.
    - Verifies via system catalogs that the index was removed after execution.
    - Recursively inspects the real plan to determine real_candidate_used and real_plan_classification.
    - Clearly distinguishes between SUCCESS, TIMEOUT, BENCHMARK_ERROR, and CLEANUP_ERROR.
    - Never runs blanket un-scoped ANALYZE across the database.
    - Tracks explicit baseline block identity and candidate linkage (Decision #5).
    """
    # Enforce deterministic prefix
    safe_index_name = (
        index_name
        if index_name.startswith(EXPERIMENTAL_INDEX_PREFIX)
        else f"{EXPERIMENTAL_INDEX_PREFIX}{index_name}"
    )

    # Ensure index_sql uses safe_index_name if it contained the un-prefixed name
    actual_index_sql = index_sql
    if index_name != safe_index_name and index_name in actual_index_sql:
        actual_index_sql = actual_index_sql.replace(index_name, safe_index_name)

    index_created = False
    cleanup_verified = False
    status = "PENDING"
    error_message = None
    benchmark_result: Optional[Dict[str, Any]] = None

    # Step 1: Capture baseline execution and plan prior to CREATE INDEX (Decision #5)
    effective_baseline_benchmark = baseline_benchmark
    if effective_baseline_benchmark is None:
        if baseline_manager is not None and query_id is not None:
            effective_baseline_benchmark = baseline_manager.get_or_create_baseline(
                query=query,
                query_id=query_id,
                repetitions=repetitions,
                warmups=warmups,
                timeout_ms=timeout_ms,
            )
        else:
            effective_baseline_benchmark = measure_baseline_block(
                query=query,
                query_id=query_id,
                repetitions=repetitions,
                warmups=warmups,
                timeout_ms=timeout_ms,
                dbname=dbname,
            )
    elif not effective_baseline_benchmark.get("baseline_block_id"):
        # Make identity explicit for shared precomputed baseline if not already set
        clean_qid = query_id or "shared"
        effective_baseline_benchmark["baseline_block_id"] = (
            f"base_{clean_qid}_shared_{abs(hash(str(effective_baseline_benchmark.get('runtimes_ms'))))}"
        )
        effective_baseline_benchmark.setdefault(
            "T_baseline", effective_baseline_benchmark.get("median_runtime_ms")
        )

    base_block_id = effective_baseline_benchmark.get("baseline_block_id") if effective_baseline_benchmark else None
    if baseline_manager is not None and base_block_id:
        baseline_manager.link_candidate_to_baseline(base_block_id, safe_index_name)

    effective_baseline_plan = baseline_plan
    if effective_baseline_plan is None and effective_baseline_benchmark:
        effective_baseline_plan = effective_baseline_benchmark.get("plan")

    # If baseline plan is still None (e.g. baseline timed out without capturing plan),
    # fallback to EXPLAIN (FORMAT JSON) to extract planner structure and cost
    if effective_baseline_plan is None:
        try:
            with get_connection(dbname=dbname) as conn:
                conn.autocommit = True
                with conn.cursor() as cur:
                    apply_benchmark_session_settings(cur)
                    cur.execute(f"EXPLAIN (FORMAT JSON) {query}")
                    res = cur.fetchone()[0]
                    effective_baseline_plan = res[0]
        except Exception:
            effective_baseline_plan = None

    baseline_root: Optional[Dict[str, Any]] = None
    if effective_baseline_plan is not None:
        if isinstance(effective_baseline_plan, list) and len(effective_baseline_plan) > 0:
            effective_baseline_plan = effective_baseline_plan[0]
        baseline_root = effective_baseline_plan.get("Plan", effective_baseline_plan)

    baseline_cost: Optional[float] = None
    if baseline_root is not None:
        try:
            baseline_cost = float(baseline_root.get("Total Cost", 0.0))
        except (ValueError, TypeError):
            baseline_cost = None

    t_baseline = (
        effective_baseline_benchmark.get("T_baseline")
        if effective_baseline_benchmark
        else None
    )
    if t_baseline is None and effective_baseline_benchmark:
        t_baseline = effective_baseline_benchmark.get("median_runtime_ms")

    # Determine dynamic candidate timeout limit: T_limit = max(30 sec, 1.5 * T_baseline)
    # If explicit non-default timeout_ms was passed (e.g. 15ms in test_timeout_cleanup), honor it.
    if timeout_ms is not None and timeout_ms != DEFAULT_TIMEOUT_MS:
        candidate_timeout_ms = float(timeout_ms)
    else:
        candidate_timeout_ms = calculate_dynamic_timeout_limit(t_baseline)

    try:
        # Step 2: Create real index on dedicated connection and commit
        with get_connection(dbname=dbname) as conn:
            with conn.cursor() as cur:
                try:
                    # Enforce a strict DDL timeout. We use max(60000, 2 * candidate_timeout)
                    # to ensure index creation doesn't hang forever, but has enough time.
                    ddl_timeout = int(max(60000, candidate_timeout_ms * 2))
                    cur.execute(f"SET statement_timeout = {ddl_timeout}")
                    cur.execute(actual_index_sql)
                    if run_analyze and table_name:
                        cur.execute(f'ANALYZE "{table_name}"')
                    conn.commit()
                    index_created = True
                except Exception as e:
                    conn.rollback()
                    if "canceling statement due to statement timeout" in str(e).lower():
                        status = "BENCHMARK_ERROR"
                        error_message = f"DDL Timeout: Failed to create experimental index within {ddl_timeout}ms."
                    else:
                        status = "BENCHMARK_ERROR"
                        error_message = f"Failed to create experimental index: {e}"

        # Step 3: If index was successfully created, benchmark the query with candidate_timeout_ms
        if index_created:
            try:
                benchmark_result = benchmark_query(
                    query=query,
                    repetitions=repetitions,
                    warmups=warmups,
                    timeout_ms=int(candidate_timeout_ms),
                    dbname=dbname,
                )
                status = benchmark_result["status"]
                error_message = benchmark_result["error_message"]
            except Exception as e:
                status = "BENCHMARK_ERROR"
                error_message = f"Benchmark query execution error: {e}"

    finally:
        # Step 4: Always drop the experimental index on dedicated autocommit connection
        if index_created:
            try:
                drop_experimental_index(safe_index_name, dbname=dbname)
                cleanup_verified = verify_index_absent(safe_index_name, dbname=dbname)
                if not cleanup_verified:
                    status = "CLEANUP_ERROR"
                    error_message = f"CRITICAL: Failed to drop experimental index '{safe_index_name}'."
            except Exception as e:
                cleanup_verified = False
                status = "CLEANUP_ERROR"
                error_message = f"CRITICAL: Exception during index teardown: {e}"
        else:
            # If creation failed, verify nothing was left behind
            cleanup_verified = verify_index_absent(safe_index_name, dbname=dbname)

    # Step 5: Inspect real execution plan and classify
    real_candidate_used = False
    real_plan_changed: Optional[bool] = None
    real_used_indexes: List[str] = []
    real_plan_classification: Optional[str] = None
    real_plan: Optional[Dict[str, Any]] = None

    if benchmark_result and benchmark_result.get("plan"):
        real_plan = benchmark_result["plan"]
        real_root = real_plan.get("Plan", real_plan)

        real_used_indexes = _collect_used_indexes(real_root)
        real_candidate_used = safe_index_name in real_used_indexes

        if baseline_root:
            is_identical = _is_plan_structurally_identical(baseline_root, real_root)
            real_plan_changed = not is_identical
        else:
            real_plan_changed = None

        if real_candidate_used:
            real_plan_classification = "candidate_used"
        elif real_plan_changed is not None and real_plan_changed:
            real_plan_classification = "changed_unused"
        elif real_plan_changed is not None and not real_plan_changed:
            real_plan_classification = "identical_plan"
    timed_out = benchmark_result.get("timed_out", False) if benchmark_result else False
    is_timeout = status == "TIMEOUT" or timed_out

    if is_timeout:
        label_is_censored = True
        actual_runtime_ms = None  # Do NOT fabricate or substitute timeout_limit as actual runtime!
        target_is_censored = True
        target_type = "bound_derived"
        y_timeout = compute_timeout_target(t_baseline, candidate_timeout_ms)
        target = y_timeout
    elif status == "SUCCESS":
        label_is_censored = False
        actual_runtime_ms = benchmark_result.get("median_runtime_ms")
        target_is_censored = False
        target_type = "observed"
        target = compute_speedup_target(t_baseline, actual_runtime_ms)
        y_timeout = compute_timeout_target(t_baseline, candidate_timeout_ms)
    else:
        label_is_censored = False
        actual_runtime_ms = None
        target_is_censored = False
        target_type = None
        target = None
        y_timeout = compute_timeout_target(t_baseline, candidate_timeout_ms)

    return {
        "index_name": safe_index_name,
        "index_sql": actual_index_sql,
        "status": status,
        "timed_out": timed_out,
        "cleanup_verified": cleanup_verified,
        "error_message": error_message,
        # Decision #6: Dynamic Timeout & Censoring Policy
        "timeout_limit_ms": candidate_timeout_ms,
        "T_limit": candidate_timeout_ms,
        "actual_runtime_ms": actual_runtime_ms,
        "label_is_censored": label_is_censored,
        "target": target,
        "target_type": target_type,
        "target_is_censored": target_is_censored,
        "y_timeout": y_timeout,
        "epsilon_ms": DEFAULT_EPSILON_MS,
        # Runtime observations
        "runtimes_ms": benchmark_result.get("runtimes_ms", []) if benchmark_result else [],
        "median_runtime_ms": benchmark_result.get("median_runtime_ms") if benchmark_result else None,
        "min_runtime_ms": benchmark_result.get("min_runtime_ms") if benchmark_result else None,
        "max_runtime_ms": benchmark_result.get("max_runtime_ms") if benchmark_result else None,
        "mean_runtime_ms": benchmark_result.get("mean_runtime_ms") if benchmark_result else None,
        "planning_times_ms": benchmark_result.get("planning_times_ms", []) if benchmark_result else [],
        "planning_time_ms": benchmark_result.get("planning_time_ms") if benchmark_result else None,
        "median_planning_time_ms": benchmark_result.get("median_planning_time_ms") if benchmark_result else None,
        "min_planning_time_ms": benchmark_result.get("min_planning_time_ms") if benchmark_result else None,
        "max_planning_time_ms": benchmark_result.get("max_planning_time_ms") if benchmark_result else None,
        "mean_planning_time_ms": benchmark_result.get("mean_planning_time_ms") if benchmark_result else None,
        "repetitions": repetitions,
        "warmups": warmups,
        "timeout_ms": timeout_ms,
        "real_candidate_used": real_candidate_used,
        "real_plan_changed": real_plan_changed,
        "plan_changed": real_plan_changed,
        "plan_change_event": bool(real_plan_changed),
        "real_used_indexes": real_used_indexes,
        "real_plan_classification": real_plan_classification,
        "plan": real_plan,
        "real_plan_signature": generate_plan_signature(real_plan) if real_plan else None,
        "real_plan_hash": generate_plan_hash(real_plan) if real_plan else None,
        # Baseline execution and plan metrics (Decision #5)
        "baseline_block_id": base_block_id,
        "baseline_created_at": effective_baseline_benchmark.get("created_at") if effective_baseline_benchmark else None,
        "baseline_sequence_number": effective_baseline_benchmark.get("sequence_number") if effective_baseline_benchmark else None,
        "T_baseline": effective_baseline_benchmark.get("T_baseline", effective_baseline_benchmark.get("median_runtime_ms")) if effective_baseline_benchmark else None,
        "baseline_status": effective_baseline_benchmark.get("status") if effective_baseline_benchmark else None,
        "baseline_timed_out": effective_baseline_benchmark.get("timed_out", False) if effective_baseline_benchmark else False,
        "baseline_runtimes_ms": effective_baseline_benchmark.get("runtimes_ms", []) if effective_baseline_benchmark else [],
        "baseline_median_runtime_ms": effective_baseline_benchmark.get("median_runtime_ms") if effective_baseline_benchmark else None,
        "baseline_min_runtime_ms": effective_baseline_benchmark.get("min_runtime_ms") if effective_baseline_benchmark else None,
        "baseline_max_runtime_ms": effective_baseline_benchmark.get("max_runtime_ms") if effective_baseline_benchmark else None,
        "baseline_mean_runtime_ms": effective_baseline_benchmark.get("mean_runtime_ms") if effective_baseline_benchmark else None,
        "baseline_planning_times_ms": effective_baseline_benchmark.get("planning_times_ms", []) if effective_baseline_benchmark else [],
        "baseline_planning_time_ms": effective_baseline_benchmark.get("planning_time_ms") if effective_baseline_benchmark else None,
        "baseline_median_planning_time_ms": effective_baseline_benchmark.get("median_planning_time_ms") if effective_baseline_benchmark else None,
        "baseline_cost": baseline_cost,
        "baseline_plan": effective_baseline_plan,
        "baseline_plan_signature": generate_plan_signature(effective_baseline_plan) if effective_baseline_plan else None,
        "baseline_plan_hash": generate_plan_hash(effective_baseline_plan) if effective_baseline_plan else None,
        # Decision #7: PostgreSQL Statistics & Maintenance Control
        "statistics_frozen": True,
        "run_analyze": run_analyze,
        "statistics_snapshot": statistics_snapshot,
        # Decision #8: JIT, GEQO, and Parallelism Control
        "session_settings": benchmark_result.get("session_settings", {"jit": "off", "max_parallel_workers_per_gather": 0, "geqo": "off"}) if benchmark_result else {"jit": "off", "max_parallel_workers_per_gather": 0, "geqo": "off"},
        "jit": benchmark_result.get("jit", "off") if benchmark_result else "off",
        "max_parallel_workers_per_gather": benchmark_result.get("max_parallel_workers_per_gather", 0) if benchmark_result else 0,
        "geqo": benchmark_result.get("geqo", "off") if benchmark_result else "off",
    }
