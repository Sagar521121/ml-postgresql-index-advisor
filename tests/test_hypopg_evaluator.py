from pathlib import Path
from src.database.connection import get_connection
from src.index_advisor.existing_indexes import get_existing_indexes, is_candidate_covered
from src.index_advisor.hypopg_evaluator import evaluate_candidate


def _assert_hypopg_empty():
    with get_connection("job_imdb") as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM hypopg();")
            rows = cur.fetchall()
            assert len(rows) == 0, f"Expected 0 active HypoPG indexes, found {len(rows)}: {rows}"


def test_identical_plan_company_type():
    """
    Test candidate: company_type(kind).
    On JOB 1a.sql, PostgreSQL planner rejects this candidate because the table is too small
    (always uses Seq Scan), yielding an identical plan where candidate_used is False.
    """
    _assert_hypopg_empty()

    q1a = Path("benchmarks/job/1a.sql").read_text(encoding="utf-8")
    candidate = {
        "table": "company_type",
        "columns": ["kind"],
        "index_type": "btree",
    }

    result = evaluate_candidate(query=q1a, candidate=candidate, dbname="job_imdb")

    print("\\n--- Test Identical Plan: company_type(kind) on 1a.sql ---")
    print(f"Hypo index name: {result['hypothetical_index_name']}")
    print(f"Baseline cost: {result['baseline_cost']:.2f}")
    print(f"Hypothetical cost: {result['hypothetical_cost']:.2f}")
    print(f"Cost reduction: {result['cost_reduction']:.2f}")
    print(f"Candidate used: {result['candidate_used']}")
    print(f"Plan classification: {result['plan_classification']}")
    print(f"Hypothetical used indexes: {result['hypothetical_used_indexes']}")
    print(f"Hypothetical has index scan: {result['hypothetical_has_index_scan']}")

    assert result["hypothetical_index_name"] is not None
    assert "btree_company_type_kind" in result["hypothetical_index_name"]
    assert result["candidate_used"] is False, "Candidate should NOT be used"
    assert result["plan_classification"] == "identical_plan", (
        f"Expected 'identical_plan', got {result['plan_classification']}"
    )
    assert result["cost_reduction"] == 0.0

    # Critical requirement: generic index scan must NOT be conflated with candidate usage!
    assert result["hypothetical_has_index_scan"] is True, (
        "Baseline indexes perform index scans"
    )
    assert result["candidate_used"] is False

    _assert_hypopg_empty()
    print("Identical plan test PASSED!")


def test_candidate_used_company_name():
    """
    Test candidate: company_name(country_code) on 10a.sql.
    PostgreSQL optimizer adopts this candidate index, reducing cost significantly.
    Yields candidate_used == True and plan_classification == 'candidate_used'.
    """
    _assert_hypopg_empty()

    q10a = Path("benchmarks/job/10a.sql").read_text(encoding="utf-8")
    candidate = {
        "table": "company_name",
        "columns": ["country_code"],
        "index_type": "btree",
    }

    result = evaluate_candidate(query=q10a, candidate=candidate, dbname="job_imdb")

    print("\n--- Test Candidate Used: company_name(country_code) on 10a.sql ---")
    print(f"Hypo index name: {result['hypothetical_index_name']}")
    print(f"Baseline cost: {result['baseline_cost']:.2f}")
    print(f"Hypothetical cost: {result['hypothetical_cost']:.2f}")
    print(f"Cost reduction: {result['cost_reduction']:.2f}")
    print(f"Candidate used: {result['candidate_used']}")
    print(f"Plan classification: {result['plan_classification']}")
    print(f"Hypothetical used indexes: {result['hypothetical_used_indexes']}")

    assert result["hypothetical_index_name"] is not None
    assert "btree_company_name_country_code" in result["hypothetical_index_name"]
    assert result["candidate_used"] is True, "Candidate index should be used in the plan"
    assert result["plan_classification"] == "candidate_used"
    assert result["cost_reduction"] > 1000.0, f"Expected substantial cost reduction, got {result['cost_reduction']}"
    assert result["hypothetical_index_name"] in result["hypothetical_used_indexes"]

    _assert_hypopg_empty()
    print("Candidate used test PASSED!")


from unittest.mock import patch

def test_changed_unused_synthetic_mock():
    """
    Deterministic synthetic unit test that directly exercises the 'changed_unused'
    classification branch. Constructs mocked baseline and hypothetical plan structures
    such that the candidate is NOT used, but the structural plan differs.
    """
    _assert_hypopg_empty()

    candidate = {
        "table": "title",
        "columns": ["production_year"],
        "index_type": "btree",
    }

    baseline_plan = {
        "Node Type": "Hash Join",
        "Total Cost": 100.0,
        "Plans": [{"Node Type": "Seq Scan", "Relation Name": "title"}]
    }

    # Structurally different plan (Nested Loop instead of Hash Join),
    # but the hypothetical index is NOT in the plan.
    hypo_plan = {
        "Node Type": "Nested Loop",
        "Total Cost": 90.0,
        "Plans": [{"Node Type": "Seq Scan", "Relation Name": "title"}]
    }

    call_count = 0
    def mock_get_plan(cur, query):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return baseline_plan, {"Plan": baseline_plan}
        else:
            return hypo_plan, {"Plan": hypo_plan}

    with patch("src.index_advisor.hypopg_evaluator._get_plan", side_effect=mock_get_plan):
        result = evaluate_candidate(query="SELECT 1", candidate=candidate, dbname="job_imdb")

    print("\\n--- Test Changed Unused: Synthetic Mock ---")
    print(f"Hypo index name: {result['hypothetical_index_name']}")
    print(f"Candidate used: {result['candidate_used']}")
    print(f"Plan changed: {result['plan_changed']}")
    print(f"Plan classification: {result['plan_classification']}")

    assert result["hypothetical_index_name"] is not None
    assert result["candidate_used"] is False, "Candidate index should NOT be used"
    assert result["plan_changed"] is True, "Plan should be considered changed"
    assert result["plan_classification"] == "changed_unused", (
        f"Expected 'changed_unused', got {result['plan_classification']}"
    )

    _assert_hypopg_empty()
    print("Changed unused test PASSED!")


def test_already_covered_candidate():
    """
    Test candidate: movie_companies(movie_id).
    This index already exists in job_imdb as an FK index ('movie_id_movie_companies').
    1. Verify existing_indexes recognizes it as covered.
    2. Verify evaluating it in HypoPG captures the index identifier and cleans up properly.
    """
    _assert_hypopg_empty()

    existing = get_existing_indexes(dbname="job_imdb")
    is_covered = is_candidate_covered("movie_companies", ["movie_id"], existing)
    assert is_covered is True, "movie_companies(movie_id) must be recognized as already covered"

    q1a = Path("benchmarks/job/1a.sql").read_text(encoding="utf-8")
    candidate = {
        "table": "movie_companies",
        "columns": ["movie_id"],
        "index_type": "btree",
    }

    result = evaluate_candidate(query=q1a, candidate=candidate, dbname="job_imdb")

    print("\n--- Test Covered Candidate: movie_companies(movie_id) on 1a.sql ---")
    print(f"Is candidate covered by existing catalog: {is_covered}")
    print(f"Hypo duplicate index name: {result['hypothetical_index_name']}")
    print(f"Cost reduction vs baseline: {result['cost_reduction']:.2f}")

    assert result["hypothetical_index_name"] is not None
    assert "btree_movie_companies_movie_id" in result["hypothetical_index_name"]

    _assert_hypopg_empty()
    print("Covered candidate test PASSED!")


def main():
    print("=" * 70)
    print("RUNNING CANDIDATE-SPECIFIC HYPOPG EVALUATION TEST SUITE")
    print("=" * 70)

    test_identical_plan_company_type()
    test_candidate_used_company_name()
    test_changed_unused_synthetic_mock()
    test_already_covered_candidate()

    print("=" * 70)
    print("ALL CANDIDATE-SPECIFIC HYPOPG TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    main()
