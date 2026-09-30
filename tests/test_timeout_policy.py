import math
from unittest.mock import patch
from psycopg.errors import QueryCanceled

from src.dataset.real_index_benchmark import (
    benchmark_with_real_index,
    build_create_index_sql,
    make_experimental_index_name,
)
from src.dataset.timeout_policy import (
    DEFAULT_EPSILON_MS,
    DEFAULT_MIN_TIMEOUT_SECONDS,
    DEFAULT_TIMEOUT_MULTIPLIER,
    calculate_dynamic_timeout_limit,
    compute_speedup_target,
    compute_timeout_target,
)
from src.features.plan_features import extract_plan_features


def test_dynamic_timeout_formula_short_baseline():
    """
    Test A & B: T_limit = max(30 sec, 1.5 * T_baseline).
    A short baseline (< 20s) must receive the 30-second minimum (30,000 ms).
    """
    # Very fast query (50 ms)
    assert calculate_dynamic_timeout_limit(50.0) == 30000.0

    # Moderate query (10 seconds = 10,000 ms)
    # 1.5 * 10,000 = 15,000 ms < 30,000 ms -> 30,000 ms
    assert calculate_dynamic_timeout_limit(10000.0) == 30000.0

    # Boundary query (20 seconds = 20,000 ms)
    # 1.5 * 20,000 = 30,000 ms -> 30,000 ms
    assert calculate_dynamic_timeout_limit(20000.0) == 30000.0

    # Missing / None / 0.0 baseline fallback
    assert calculate_dynamic_timeout_limit(None) == 30000.0
    assert calculate_dynamic_timeout_limit(0.0) == 30000.0
    assert calculate_dynamic_timeout_limit(-10.0) == 30000.0


def test_dynamic_timeout_formula_long_baseline():
    """
    Test A & C: A long baseline (> 20s) must receive the 1.5x multiplier.
    """
    # 40-second baseline (40,000 ms) -> 1.5 * 40,000 = 60,000 ms
    assert calculate_dynamic_timeout_limit(40000.0) == 60000.0

    # 100-second baseline (100,000 ms) -> 1.5 * 100,000 = 150,000 ms
    assert calculate_dynamic_timeout_limit(100000.0) == 150000.0


def test_successful_candidate_metadata():
    """
    Test D: A successful candidate has normal runtime metadata:
    - status = SUCCESS
    - actual_runtime_ms = median Execution Time
    - label_is_censored = False
    - target = log((T_baseline + 1.0) / (actual_runtime_ms + 1.0))
    - target_type = "observed"
    - target_is_censored = False
    """
    mock_baseline = {
        "baseline_block_id": "base_test_seq1",
        "median_runtime_ms": 100.0,
        "T_baseline": 100.0,
        "status": "SUCCESS",
        "runtimes_ms": [100.0] * 5,
        "plan": {"Plan": {"Node Type": "Seq Scan", "Total Cost": 500.0}},
    }
    mock_candidate_plan = {
        "Plan": {"Node Type": "Index Scan", "Index Name": "exp_idx_test_col", "Total Cost": 50.0},
        "Planning Time": 0.5,
        "Execution Time": 20.0,
    }

    index_name = make_experimental_index_name("company_type", ["kind"])
    index_sql = build_create_index_sql(index_name, "company_type", ["kind"])

    with patch("src.dataset.real_benchmark_executor._run_explain_analyze", return_value=mock_candidate_plan), \
         patch("src.dataset.real_index_benchmark.drop_experimental_index", return_value=True), \
         patch("src.dataset.real_index_benchmark.verify_index_absent", return_value=True), \
         patch("src.dataset.real_index_benchmark.get_connection"):

        result = benchmark_with_real_index(
            query="SELECT 1;",
            index_sql=index_sql,
            index_name=index_name,
            table_name="company_type",
            baseline_benchmark=mock_baseline,
        )

    assert result["status"] == "SUCCESS"
    assert result["timed_out"] is False
    assert result["label_is_censored"] is False
    assert result["actual_runtime_ms"] == 20.0
    assert result["timeout_limit_ms"] == 30000.0  # max(30s, 1.5 * 100ms) = 30s
    assert result["target_type"] == "observed"
    assert result["target_is_censored"] is False

    # Target calculation check: log((100.0 + 1.0) / (20.0 + 1.0)) = log(101.0 / 21.0)
    expected_target = math.log((100.0 + 1.0) / (20.0 + 1.0))
    assert math.isclose(result["target"], expected_target, rel_tol=1e-6)


def test_timeout_candidate_metadata_and_censoring():
    """
    Test E, H & I: When candidate times out:
    - status = TIMEOUT
    - actual_runtime_ms = NULL (None)
    - label_is_censored = TRUE
    - timeout_limit recorded
    - y_timeout = log((T_baseline + 1.0) / (T_limit + 1.0)) with epsilon = 1.0 ms
    - target_type = "bound_derived"
    - target_is_censored = True
    """
    # 40-second baseline (40,000 ms) -> T_limit = 60,000 ms
    mock_baseline = {
        "baseline_block_id": "base_test_seq1",
        "median_runtime_ms": 40000.0,
        "T_baseline": 40000.0,
        "status": "SUCCESS",
        "runtimes_ms": [40000.0] * 5,
        "plan": {"Plan": {"Node Type": "Seq Scan", "Total Cost": 5000.0}},
    }

    def mock_explain_analyze(cur, query, timeout_ms):
        raise QueryCanceled("statement timeout")

    index_name = make_experimental_index_name("company_type", ["kind"])
    index_sql = build_create_index_sql(index_name, "company_type", ["kind"])

    with patch("src.dataset.real_benchmark_executor._run_explain_analyze", side_effect=mock_explain_analyze), \
         patch("src.dataset.real_index_benchmark.drop_experimental_index", return_value=True), \
         patch("src.dataset.real_index_benchmark.verify_index_absent", return_value=True), \
         patch("src.dataset.real_index_benchmark.get_connection"):

        result = benchmark_with_real_index(
            query="SELECT 1;",
            index_sql=index_sql,
            index_name=index_name,
            table_name="company_type",
            baseline_benchmark=mock_baseline,
        )

    assert result["status"] == "TIMEOUT"
    assert result["timed_out"] is True

    # Crucial Requirement 3: actual_runtime must be NULL, never timeout_limit!
    assert result["actual_runtime_ms"] is None, f"Expected actual_runtime_ms to be None, got {result['actual_runtime_ms']}"
    assert result["label_is_censored"] is True

    # Crucial Requirement 1 & 4: T_limit = 60,000 ms recorded
    assert result["timeout_limit_ms"] == 60000.0
    assert result["T_limit"] == 60000.0
    assert result["T_baseline"] == 40000.0

    # Crucial Requirement 7 & 8: Bound-derived timeout target with epsilon = 1.0 ms
    assert result["target_type"] == "bound_derived"
    assert result["target_is_censored"] is True
    expected_y_timeout = math.log((40000.0 + 1.0) / (60000.0 + 1.0))
    assert math.isclose(result["target"], expected_y_timeout, rel_tol=1e-6)
    assert math.isclose(result["y_timeout"], expected_y_timeout, rel_tol=1e-6)


def test_partial_timeout_preserves_completed_observations_only():
    """
    Test F: When timeout occurs after some measured repetitions have completed:
    - completed observations are preserved in runtimes_ms
    - missing runtime is NOT fabricated
    - actual_runtime_ms remains NULL
    - label_is_censored = TRUE
    - target = bound-derived timeout target
    """
    mock_baseline = {
        "baseline_block_id": "base_test_seq1",
        "median_runtime_ms": 100.0,
        "T_baseline": 100.0,
        "status": "SUCCESS",
        "runtimes_ms": [100.0] * 5,
        "plan": {"Plan": {"Node Type": "Seq Scan"}},
    }

    call_count = 0

    def mock_explain_analyze(cur, query, timeout_ms):
        nonlocal call_count
        call_count += 1
        # 1 warmup succeeds
        if call_count == 1:
            return {"Plan": {}, "Planning Time": 0.5, "Execution Time": 120.0}
        # Repetition 1 completes
        if call_count == 2:
            return {"Plan": {}, "Planning Time": 0.5, "Execution Time": 150.0}
        # Repetition 2 times out
        raise QueryCanceled("statement timeout")

    index_name = make_experimental_index_name("company_type", ["kind"])
    index_sql = build_create_index_sql(index_name, "company_type", ["kind"])

    with patch("src.dataset.real_benchmark_executor._run_explain_analyze", side_effect=mock_explain_analyze), \
         patch("src.dataset.real_index_benchmark.drop_experimental_index", return_value=True), \
         patch("src.dataset.real_index_benchmark.verify_index_absent", return_value=True), \
         patch("src.dataset.real_index_benchmark.get_connection"):

        result = benchmark_with_real_index(
            query="SELECT 1;",
            index_sql=index_sql,
            index_name=index_name,
            table_name="company_type",
            repetitions=2,
            warmups=1,
            baseline_benchmark=mock_baseline,
        )

    assert result["status"] == "TIMEOUT"
    assert result["timed_out"] is True
    assert result["label_is_censored"] is True

    # Completed rep 1 observation preserved:
    assert result["runtimes_ms"] == [150.0]

    # actual_runtime_ms must remain None because the candidate timed out:
    assert result["actual_runtime_ms"] is None

    # Target is bound-derived timeout target, NOT based on the partial rep:
    assert result["target_type"] == "bound_derived"
    assert result["target_is_censored"] is True
    expected_y_timeout = math.log((100.0 + 1.0) / (30000.0 + 1.0))
    assert math.isclose(result["target"], expected_y_timeout, rel_tol=1e-6)


def test_zero_completed_observations_produces_null_statistics():
    """
    Test G: When timeout occurs with zero completed measured repetitions,
    runtime summary statistics must remain NULL (None).
    """
    mock_baseline = {
        "baseline_block_id": "base_test_seq1",
        "median_runtime_ms": 50.0,
        "T_baseline": 50.0,
        "status": "SUCCESS",
        "runtimes_ms": [50.0] * 5,
        "plan": {"Plan": {"Node Type": "Seq Scan"}},
    }

    def mock_explain_analyze(cur, query, timeout_ms):
        raise QueryCanceled("statement timeout during warmup")

    index_name = make_experimental_index_name("company_type", ["kind"])
    index_sql = build_create_index_sql(index_name, "company_type", ["kind"])

    with patch("src.dataset.real_benchmark_executor._run_explain_analyze", side_effect=mock_explain_analyze), \
         patch("src.dataset.real_index_benchmark.drop_experimental_index", return_value=True), \
         patch("src.dataset.real_index_benchmark.verify_index_absent", return_value=True), \
         patch("src.dataset.real_index_benchmark.get_connection"):

        result = benchmark_with_real_index(
            query="SELECT 1;",
            index_sql=index_sql,
            index_name=index_name,
            table_name="company_type",
            baseline_benchmark=mock_baseline,
        )

    assert result["status"] == "TIMEOUT"
    assert result["runtimes_ms"] == []
    assert result["median_runtime_ms"] is None
    assert result["mean_runtime_ms"] is None
    assert result["min_runtime_ms"] is None
    assert result["max_runtime_ms"] is None
    assert result["actual_runtime_ms"] is None
    assert result["label_is_censored"] is True


def test_timeout_policy_not_leaked_into_ml_features():
    """
    Test 9: Verify that timeout status, actual runtime, censoring flag,
    and timeout target are NEVER included in the ML feature vector.
    """
    plan = [
        {
            "Plan": {
                "Node Type": "Seq Scan",
                "Relation Name": "title",
                "Startup Cost": 0.0,
                "Total Cost": 250.0,
                "Plan Rows": 500,
                "Plan Width": 24,
            }
        }
    ]

    features = extract_plan_features(plan)

    # Verify structural features exist
    assert features["root_node_type"] == "Seq Scan"
    assert features["root_total_cost"] == 250.0

    # Verify NO timeout policy fields leaked into feature vector
    forbidden_keys = [
        "status",
        "actual_runtime_ms",
        "actual_runtime",
        "label_is_censored",
        "target",
        "y_timeout",
        "target_type",
        "target_is_censored",
        "timeout_limit_ms",
        "T_limit",
    ]
    for key in forbidden_keys:
        assert key not in features, f"Feature leak detected: '{key}' found in feature vector!"


def main():
    print("=" * 70)
    print("RUNNING DECISION #6 DYNAMIC TIMEOUT & CENSORING POLICY TESTS")
    print("=" * 70)

    test_dynamic_timeout_formula_short_baseline()
    print("test_dynamic_timeout_formula_short_baseline: PASSED")

    test_dynamic_timeout_formula_long_baseline()
    print("test_dynamic_timeout_formula_long_baseline: PASSED")

    test_successful_candidate_metadata()
    print("test_successful_candidate_metadata: PASSED")

    test_timeout_candidate_metadata_and_censoring()
    print("test_timeout_candidate_metadata_and_censoring: PASSED")

    test_partial_timeout_preserves_completed_observations_only()
    print("test_partial_timeout_preserves_completed_observations_only: PASSED")

    test_zero_completed_observations_produces_null_statistics()
    print("test_zero_completed_observations_produces_null_statistics: PASSED")

    test_timeout_policy_not_leaked_into_ml_features()
    print("test_timeout_policy_not_leaked_into_ml_features: PASSED")

    print("=" * 70)
    print("ALL DECISION #6 TIMEOUT & CENSORING TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    main()
