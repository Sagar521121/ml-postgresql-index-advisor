from pathlib import Path
from src.database.connection import get_connection
from src.dataset.real_index_benchmark import (
    EXPERIMENTAL_INDEX_PREFIX,
    benchmark_with_real_index,
    build_create_index_sql,
    cleanup_leftover_experimental_indexes,
    drop_experimental_index,
    make_experimental_index_name,
    verify_index_absent,
)


def test_startup_cleanup_sweep():
    """Verify that leftover experimental indexes are discovered and dropped."""
    test_index_name = f"{EXPERIMENTAL_INDEX_PREFIX}sweep_test_dummy"

    # 1. Deliberately create a leftover experimental index
    with get_connection("job_imdb") as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'DROP INDEX IF EXISTS "{test_index_name}"')
            cur.execute(f'CREATE INDEX "{test_index_name}" ON company_type (kind)')

    assert not verify_index_absent(test_index_name, "job_imdb"), "Index should exist in catalog"

    # 2. Run startup sweep
    dropped = cleanup_leftover_experimental_indexes("job_imdb")
    print(f"Sweep dropped indexes: {dropped}")
    assert test_index_name in dropped, f"Expected {test_index_name} in dropped list"
    assert verify_index_absent(test_index_name, "job_imdb"), "Index should be removed from catalog"
    print("Startup cleanup sweep test PASSED!")


def test_timeout_cleanup():
    """
    Critical Test: Trigger a statement timeout during execution and verify that
    the experimental index is STILL cleaned up and removed from PostgreSQL catalogs.
    """
    index_name = make_experimental_index_name("company_type", ["kind"])
    index_sql = build_create_index_sql(index_name, "company_type", ["kind"])

    # Pre-condition: index does not exist
    drop_experimental_index(index_name, "job_imdb")
    assert verify_index_absent(index_name, "job_imdb")

    # Use a real JOB query with an impossibly short timeout (15ms) to guarantee QueryCanceled
    job_1a_path = Path("benchmarks/job/1a.sql")
    query = job_1a_path.read_text(encoding="utf-8") if job_1a_path.exists() else "SELECT pg_sleep(1);"

    result = benchmark_with_real_index(
        query=query,
        index_sql=index_sql,
        index_name=index_name,
        repetitions=2,
        warmups=1,
        timeout_ms=1,  # 1ms statement timeout guarantees cancellation on JOB 1a
        dbname="job_imdb",
    )

    print("Timeout benchmark result:")
    print(f"  status: {result['status']}")
    print(f"  timed_out: {result['timed_out']}")
    print(f"  cleanup_verified: {result['cleanup_verified']}")
    print(f"  median_runtime_ms: {result['median_runtime_ms']}")

    # Assertions
    assert result["status"] == "TIMEOUT", f"Expected status 'TIMEOUT', got {result['status']}"
    assert result["timed_out"] is True, "Expected timed_out to be True"
    assert result["cleanup_verified"] is True, "Expected cleanup_verified to be True"

    # Direct catalog check: verify index does NOT exist in pg_class/pg_index
    is_absent = verify_index_absent(index_name, "job_imdb")
    assert is_absent, f"CRITICAL LEAK: Index {index_name} still found in PostgreSQL catalog!"

    print("Deliberate timeout cleanup test PASSED!")


def test_successful_benchmark_cleanup():
    """Verify that a successful benchmark execution cleans up its experimental index."""
    index_name = make_experimental_index_name("company_type", ["kind"])
    index_sql = build_create_index_sql(index_name, "company_type", ["kind"])

    drop_experimental_index(index_name, "job_imdb")
    assert verify_index_absent(index_name, "job_imdb")

    fast_query = "SELECT min(ct.kind) FROM company_type ct WHERE ct.kind = 'production companies';"

    result = benchmark_with_real_index(
        query=fast_query,
        index_sql=index_sql,
        index_name=index_name,
        repetitions=2,
        warmups=1,
        timeout_ms=10000,
        dbname="job_imdb",
    )

    print("Success benchmark result:")
    print(f"  status: {result['status']}")
    print(f"  cleanup_verified: {result['cleanup_verified']}")
    print(f"  median_runtime_ms: {result['median_runtime_ms']}")

    assert result["status"] == "SUCCESS", f"Expected SUCCESS, got {result['status']}"
    assert result["timed_out"] is False
    assert result["cleanup_verified"] is True
    assert verify_index_absent(index_name, "job_imdb"), "Index must be absent after success"

    print("Successful benchmark cleanup test PASSED!")


def test_benchmark_error_cleanup():
    """Verify that a benchmark syntax/table error still cleans up the experimental index."""
    index_name = make_experimental_index_name("company_type", ["kind"])
    index_sql = build_create_index_sql(index_name, "company_type", ["kind"])

    drop_experimental_index(index_name, "job_imdb")
    assert verify_index_absent(index_name, "job_imdb")

    bad_query = "SELECT * FROM nonexistent_table_xyz_12345;"

    result = benchmark_with_real_index(
        query=bad_query,
        index_sql=index_sql,
        index_name=index_name,
        repetitions=1,
        warmups=0,
        timeout_ms=5000,
        dbname="job_imdb",
    )

    print("Error benchmark result:")
    print(f"  status: {result['status']}")
    print(f"  cleanup_verified: {result['cleanup_verified']}")

    assert result["status"] == "BENCHMARK_ERROR", f"Expected BENCHMARK_ERROR, got {result['status']}"
    assert result["cleanup_verified"] is True
    assert verify_index_absent(index_name, "job_imdb"), "Index must be absent after error"

    print("Benchmark error cleanup test PASSED!")


def main():
    print("=" * 60)
    print("RUNNING REAL-INDEX CLEANUP & TIMEOUT TEST SUITE")
    print("=" * 60)

    test_startup_cleanup_sweep()
    print("-" * 60)
    test_timeout_cleanup()
    print("-" * 60)
    test_successful_benchmark_cleanup()
    print("-" * 60)
    test_benchmark_error_cleanup()
    print("=" * 60)
    print("ALL CLEANUP & TIMEOUT TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    main()
