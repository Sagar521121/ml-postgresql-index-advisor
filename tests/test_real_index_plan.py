from pathlib import Path
from src.database.connection import get_connection
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


def test_real_index_used():
    """
    Test candidate where the real index IS ACTUALLY USED.
    Query: 11a.sql
    Candidate: keyword(keyword)
    Index: exp_idx_keyword_keyword
    """
    _assert_clean_environment()

    q11a_path = Path("benchmarks/job/11a.sql")
    query = q11a_path.read_text(encoding="utf-8")

    index_name = make_experimental_index_name("keyword", ["keyword"])
    index_sql = build_create_index_sql(index_name, "keyword", ["keyword"])

    result = benchmark_with_real_index(
        query=query,
        index_sql=index_sql,
        index_name=index_name,
        table_name="keyword",
        repetitions=1,
        warmups=0,
        timeout_ms=10000,
        dbname="job_imdb",
    )

    print("\n--- Test Real Index Used: keyword(keyword) on 11a.sql ---")
    print(f"Status: {result['status']}")
    print(f"Index name: {result['index_name']}")
    print(f"Real candidate used: {result['real_candidate_used']}")
    print(f"Real plan changed: {result['real_plan_changed']}")
    print(f"Real plan classification: {result['real_plan_classification']}")
    print(f"Real used indexes: {result['real_used_indexes']}")
    print(f"Runtime ms: {result['median_runtime_ms']}")
    print(f"Cleanup verified: {result['cleanup_verified']}")

    assert result["status"] == "SUCCESS", f"Expected SUCCESS, got {result['status']}"
    assert result["cleanup_verified"] is True
    assert result["real_candidate_used"] is True, "Candidate index should be used in the plan"
    assert result["real_plan_changed"] is True, "Plan should be changed by the index"
    assert result["real_plan_classification"] == "candidate_used"
    assert index_name in result["real_used_indexes"]
    assert verify_index_absent(index_name, "job_imdb"), "Index must be absent after benchmark"

    _assert_clean_environment()
    print("Real index used test PASSED!")


def test_real_index_not_used():
    """
    Test candidate where the real index is NOT USED.
    Query: 1a.sql
    Candidate: company_type(kind)
    Index: exp_idx_company_type_kind
    """
    _assert_clean_environment()

    q1a_path = Path("benchmarks/job/1a.sql")
    query = q1a_path.read_text(encoding="utf-8")

    index_name = make_experimental_index_name("company_type", ["kind"])
    index_sql = build_create_index_sql(index_name, "company_type", ["kind"])

    result = benchmark_with_real_index(
        query=query,
        index_sql=index_sql,
        index_name=index_name,
        table_name="company_type",
        repetitions=1,
        warmups=0,
        timeout_ms=10000,
        dbname="job_imdb",
    )

    print("\n--- Test Real Index NOT Used: company_type(kind) on 1a.sql ---")
    print(f"Status: {result['status']}")
    print(f"Index name: {result['index_name']}")
    print(f"Real candidate used: {result['real_candidate_used']}")
    print(f"Real plan changed: {result['real_plan_changed']}")
    print(f"Real plan classification: {result['real_plan_classification']}")
    print(f"Real used indexes: {result['real_used_indexes']}")
    print(f"Runtime ms: {result['median_runtime_ms']}")
    print(f"Cleanup verified: {result['cleanup_verified']}")

    assert result["status"] == "SUCCESS", f"Expected SUCCESS, got {result['status']}"
    assert result["cleanup_verified"] is True
    assert result["real_candidate_used"] is False, "Candidate index should NOT be used"
    assert result["real_plan_changed"] is False, "Plan should be identical to baseline"
    assert result["real_plan_classification"] == "identical_plan"
    assert index_name not in result["real_used_indexes"]

    # Critical requirement: Generic index scans on baseline tables (movie_companies, title)
    # must NOT trigger candidate usage!
    assert len(result["real_used_indexes"]) > 0, "Baseline indexes should be present"
    assert verify_index_absent(index_name, "job_imdb"), "Index must be absent after benchmark"

    _assert_clean_environment()
    print("Real index NOT used test PASSED!")


def main():
    print("=" * 70)
    print("RUNNING REAL INDEXED EXECUTION PLAN CAPTURE & CLASSIFICATION TESTS")
    print("=" * 70)

    cleanup_leftover_experimental_indexes("job_imdb")

    test_real_index_used()
    test_real_index_not_used()

    print("=" * 70)
    print("ALL REAL INDEX PLAN CLASSIFICATION TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    main()
