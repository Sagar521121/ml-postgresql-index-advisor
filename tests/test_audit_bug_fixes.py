import statistics
from pathlib import Path
from unittest.mock import patch
from psycopg.errors import QueryCanceled
from src.database.connection import get_connection
from src.dataset.real_benchmark_executor import benchmark_query
from src.dataset.real_index_benchmark import (
    benchmark_with_real_index,
    build_create_index_sql,
    cleanup_leftover_experimental_indexes,
    make_experimental_index_name,
    verify_index_absent,
)


def _assert_clean_environment():
    """Verify that no experimental indexes or active HypoPG indexes linger."""
    with get_connection("job_imdb") as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM hypopg();")
            hypo_rows = cur.fetchall()
            assert len(hypo_rows) == 0, f"HypoPG not empty: {hypo_rows}"

            cur.execute(
                """
                SELECT c.relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relname LIKE 'exp_idx_%';
                """
            )
            exp_rows = cur.fetchall()
            assert len(exp_rows) == 0, f"Leftover experimental indexes: {exp_rows}"


def test_bug1_real_baseline_runtime_standalone():
    """
    Bug 1 Test: Standalone execution must capture real baseline execution runtimes,
    summary metrics, and plan/cost before creating the experimental index.
    """
    _assert_clean_environment()

    fast_query = "SELECT min(ct.kind) FROM company_type ct WHERE ct.kind = 'production companies';"
    index_name = make_experimental_index_name("company_type", ["kind"])
    index_sql = build_create_index_sql(index_name, "company_type", ["kind"])

    result = benchmark_with_real_index(
        query=fast_query,
        index_sql=index_sql,
        index_name=index_name,
        table_name="company_type",
        repetitions=2,
        warmups=1,
        timeout_ms=10000,
        dbname="job_imdb",
    )

    print("\n--- Test Bug 1: Real Baseline Runtime (Standalone) ---")
    print(f"Status: {result['status']}")
    print(f"Baseline status: {result['baseline_status']}")
    print(f"Baseline runtimes: {result['baseline_runtimes_ms']}")
    print(f"Baseline median ms: {result['baseline_median_runtime_ms']}")
    print(f"Baseline mean ms: {result['baseline_mean_runtime_ms']}")
    print(f"Baseline cost: {result['baseline_cost']}")
    print(f"Indexed median ms: {result['median_runtime_ms']}")

    # Baseline execution checks
    assert result["baseline_status"] == "SUCCESS", f"Expected baseline SUCCESS, got {result['baseline_status']}"
    assert result["baseline_timed_out"] is False
    assert isinstance(result["baseline_runtimes_ms"], list)
    assert len(result["baseline_runtimes_ms"]) == 2
    assert result["baseline_median_runtime_ms"] is not None and result["baseline_median_runtime_ms"] > 0
    assert result["baseline_mean_runtime_ms"] is not None and result["baseline_mean_runtime_ms"] > 0
    assert result["baseline_min_runtime_ms"] is not None and result["baseline_min_runtime_ms"] > 0
    assert result["baseline_max_runtime_ms"] is not None and result["baseline_max_runtime_ms"] > 0

    # Baseline plan and cost checks
    assert result["baseline_cost"] is not None and result["baseline_cost"] > 0
    assert result["baseline_plan"] is not None
    assert "Plan" in result["baseline_plan"]

    # Indexed query checks & cleanup verification
    assert result["status"] == "SUCCESS"
    assert result["cleanup_verified"] is True
    assert verify_index_absent(index_name, "job_imdb")

    _assert_clean_environment()
    print("Test Bug 1 (Standalone) PASSED!")


def test_bug1_real_baseline_runtime_shared():
    """
    Bug 1 Test: When a pre-computed baseline benchmark is supplied, the pipeline
    must reuse it without re-executing, preserving baseline runtimes and plan/cost.
    """
    _assert_clean_environment()

    fast_query = "SELECT min(ct.kind) FROM company_type ct WHERE ct.kind = 'production companies';"
    precomputed_baseline = benchmark_query(
        query=fast_query,
        repetitions=2,
        warmups=1,
        timeout_ms=10000,
        dbname="job_imdb",
    )

    index_name = make_experimental_index_name("company_type", ["kind"])
    index_sql = build_create_index_sql(index_name, "company_type", ["kind"])

    result = benchmark_with_real_index(
        query=fast_query,
        index_sql=index_sql,
        index_name=index_name,
        table_name="company_type",
        repetitions=2,
        warmups=1,
        timeout_ms=10000,
        dbname="job_imdb",
        baseline_benchmark=precomputed_baseline,
    )

    print("\n--- Test Bug 1: Real Baseline Runtime (Shared / Pre-computed) ---")
    print(f"Precomputed baseline median: {precomputed_baseline['median_runtime_ms']}")
    print(f"Result baseline median: {result['baseline_median_runtime_ms']}")

    assert result["baseline_status"] == precomputed_baseline["status"]
    assert result["baseline_runtimes_ms"] == precomputed_baseline["runtimes_ms"]
    assert result["baseline_median_runtime_ms"] == precomputed_baseline["median_runtime_ms"]
    assert result["baseline_cost"] is not None and result["baseline_cost"] > 0
    assert result["cleanup_verified"] is True

    _assert_clean_environment()
    print("Test Bug 1 (Shared) PASSED!")


def test_bug2_timeout_mean_zero_completed():
    """
    Bug 2 Test: When a query times out with 0 completed repetitions (e.g. during warmup),
    the timeout boundary must NOT be treated as a completed runtime.
    mean_runtime_ms and median_runtime_ms must be None, NOT float(timeout_ms).
    """
    _assert_clean_environment()

    job_1a_path = Path("benchmarks/job/1a.sql")
    query = job_1a_path.read_text(encoding="utf-8") if job_1a_path.exists() else "SELECT pg_sleep(1);"

    # 10ms timeout guarantees cancellation on JOB 1a
    result = benchmark_query(
        query=query,
        repetitions=2,
        warmups=1,
        timeout_ms=1,  # 1ms timeout guarantees cancellation on JOB 1a
        dbname="job_imdb",
    )

    print("\n--- Test Bug 2: Timeout With Zero Completed Repetitions ---")
    print(f"Status: {result['status']}")
    print(f"Timed out: {result['timed_out']}")
    print(f"Runtimes: {result['runtimes_ms']}")
    print(f"Mean runtime ms: {result['mean_runtime_ms']}")
    print(f"Median runtime ms: {result['median_runtime_ms']}")

    assert result["status"] == "TIMEOUT"
    assert result["timed_out"] is True
    assert result["runtimes_ms"] == []
    # Key Bug 2 Fix: Must be None, NEVER 10.0 (the timeout boundary)!
    assert result["mean_runtime_ms"] is None, f"Expected None, got {result['mean_runtime_ms']}"
    assert result["median_runtime_ms"] is None, f"Expected None, got {result['median_runtime_ms']}"
    assert result["min_runtime_ms"] is None
    assert result["max_runtime_ms"] is None

    _assert_clean_environment()
    print("Test Bug 2 (Zero Completed) PASSED!")


def test_bug2_timeout_mean_partial_completed():
    """
    Bug 2 Test: When rep 1 completes and rep 2 times out, mean_runtime_ms must
    be calculated ONLY over completed repetitions, NEVER appending float(timeout_ms).
    """
    fake_plan = {
        "Execution Time": 150.0,
        "Planning Time": 1.5,
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "test_table",
        },
    }

    call_count = 0

    def mock_explain_analyze(cur, query, timeout_ms):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return fake_plan
        raise QueryCanceled("canceling statement due to statement timeout")

    with patch("src.dataset.real_benchmark_executor._run_explain_analyze", side_effect=mock_explain_analyze):
        result = benchmark_query(
            query="SELECT 1;",
            repetitions=2,
            warmups=0,
            timeout_ms=30000,
            dbname="job_imdb",
        )

    print("\n--- Test Bug 2: Timeout With Partial Completed Repetitions ---")
    print(f"Status: {result['status']}")
    print(f"Timed out: {result['timed_out']}")
    print(f"Runtimes: {result['runtimes_ms']}")
    print(f"Mean runtime ms: {result['mean_runtime_ms']}")
    print(f"Median runtime ms: {result['median_runtime_ms']}")

    assert result["status"] == "TIMEOUT"
    assert result["timed_out"] is True
    assert result["runtimes_ms"] == [150.0]
    # Key Bug 2 Fix: mean must be 150.0 (from runtimes), NOT (150.0 + 30000.0)/2 = 15075.0!
    assert result["mean_runtime_ms"] == 150.0, f"Expected 150.0, got {result['mean_runtime_ms']}"
    assert result["median_runtime_ms"] == 150.0
    assert result["min_runtime_ms"] == 150.0
    assert result["max_runtime_ms"] == 150.0

    print("Test Bug 2 (Partial Completed) PASSED!")


def main():
    print("=" * 70)
    print("RUNNING FOCUSED TESTS FOR BENCHMARK AUDIT BUG FIXES")
    print("=" * 70)

    cleanup_leftover_experimental_indexes("job_imdb")

    test_bug1_real_baseline_runtime_standalone()
    test_bug1_real_baseline_runtime_shared()
    test_bug2_timeout_mean_zero_completed()
    test_bug2_timeout_mean_partial_completed()

    print("=" * 70)
    print("ALL AUDIT BUG FIX TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    main()
