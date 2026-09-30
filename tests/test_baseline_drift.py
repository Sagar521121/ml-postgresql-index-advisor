from unittest.mock import patch
from src.dataset.baseline_manager import (
    BaselineManager,
    measure_baseline_block,
)
from src.dataset.real_index_benchmark import (
    benchmark_with_real_index,
    build_create_index_sql,
    make_experimental_index_name,
)
from src.features.plan_features import extract_plan_features


def test_baseline_measurement_protocol():
    """Verify that measure_baseline_block uses exactly 2 warmups + 5 measured runs."""
    call_records = []

    def mock_explain_analyze(cur, query, timeout_ms):
        call_idx = len(call_records) + 1
        call_records.append(call_idx)
        return {
            "Plan": {"Node Type": "Seq Scan", "Relation Name": "title", "Total Cost": 150.0},
            "Planning Time": 0.6,
            "Execution Time": float(call_idx * 10),
        }

    with patch("src.dataset.real_benchmark_executor._run_explain_analyze", side_effect=mock_explain_analyze):
        base_block = measure_baseline_block(
            query="SELECT * FROM title;",
            query_id="test_q1",
            dbname="job_imdb",
        )

    assert base_block["status"] == "SUCCESS"
    assert base_block["warmups"] == 2
    assert base_block["repetitions"] == 5
    assert len(call_records) == 7, f"Expected 7 executions (2 warmups + 5 measured), got {len(call_records)}"
    # Warmups (calls 1, 2) excluded from runtimes_ms
    assert base_block["runtimes_ms"] == [30.0, 40.0, 50.0, 60.0, 70.0]
    assert base_block["cost"] == 150.0


def test_baseline_median_and_raw_runtimes_preserved():
    """
    Verify that:
    - All 5 raw baseline runtimes are preserved.
    - T_baseline is correctly calculated as the median.
    - Median differs from mean on asymmetric data.
    """
    asymmetric_times = [10.0, 11.0, 12.0, 13.0, 104.0]
    # Median = 12.0, Mean = 30.0
    plans = [
        {"Plan": {"Node Type": "Seq Scan", "Total Cost": 50.0}, "Planning Time": 1.0, "Execution Time": t}
        for t in asymmetric_times
    ]

    call_count = 0

    def mock_explain_analyze(cur, query, timeout_ms):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return {"Plan": {}, "Planning Time": 0.5, "Execution Time": 999.0}
        return plans[call_count - 3]

    with patch("src.dataset.real_benchmark_executor._run_explain_analyze", side_effect=mock_explain_analyze):
        base_block = measure_baseline_block("SELECT 1;", query_id="asym_test")

    assert base_block["runtimes_ms"] == asymmetric_times
    assert len(base_block["runtimes_ms"]) == 5
    assert base_block["median_runtime_ms"] == 12.0
    assert base_block["T_baseline"] == 12.0
    assert base_block["mean_runtime_ms"] == 30.0
    assert base_block["T_baseline"] != base_block["mean_runtime_ms"]


def test_baseline_planning_time_separate():
    """Verify that baseline planning times are collected and kept separate from T_baseline."""
    planning_times = [0.8, 1.2, 0.9, 1.5, 1.1]
    exec_times = [40.0, 42.0, 41.0, 43.0, 40.5]

    call_count = 0

    def mock_explain_analyze(cur, query, timeout_ms):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return {"Plan": {}, "Planning Time": 0.5, "Execution Time": 999.0}
        idx = call_count - 3
        return {
            "Plan": {"Node Type": "Seq Scan", "Total Cost": 10.0},
            "Planning Time": planning_times[idx],
            "Execution Time": exec_times[idx],
        }

    with patch("src.dataset.real_benchmark_executor._run_explain_analyze", side_effect=mock_explain_analyze):
        base_block = measure_baseline_block("SELECT 1;", query_id="plan_sep_test")

    assert base_block["planning_times_ms"] == planning_times
    assert len(base_block["planning_times_ms"]) == 5
    assert base_block["median_planning_time_ms"] == 1.1
    assert base_block["T_baseline"] == 41.0
    # T_baseline must not include planning time
    assert base_block["T_baseline"] not in [41.0 + 1.1, 42.1]


def test_baseline_identity_preserved():
    """Verify that baseline blocks have unique, non-empty IDs, sequence numbers, and timestamps."""
    call_count = 0

    def mock_explain_analyze(cur, query, timeout_ms):
        nonlocal call_count
        call_count += 1
        return {"Plan": {"Node Type": "Seq Scan", "Total Cost": 10.0}, "Planning Time": 0.5, "Execution Time": 20.0}

    with patch("src.dataset.real_benchmark_executor._run_explain_analyze", side_effect=mock_explain_analyze):
        block1 = measure_baseline_block("SELECT 1;", query_id="1a", sequence_number=1)
        block2 = measure_baseline_block("SELECT 1;", query_id="1a", sequence_number=2)

    assert block1["baseline_block_id"].startswith("base_1a_seq1_")
    assert block2["baseline_block_id"].startswith("base_1a_seq2_")
    assert block1["baseline_block_id"] != block2["baseline_block_id"]
    assert block1["sequence_number"] == 1
    assert block2["sequence_number"] == 2
    assert block1["created_at"] is not None
    assert block2["created_at"] is not None


def test_fresh_baseline_without_overwriting():
    """
    Verify BaselineManager drift control:
    - Fresh baseline can be created without overwriting previous baselines.
    - History preserves all baseline blocks in chronological order.
    - Each block can be looked up by its unique ID.
    """
    manager = BaselineManager(dbname="job_imdb")

    call_count = 0

    def mock_explain_analyze(cur, query, timeout_ms):
        nonlocal call_count
        call_count += 1
        return {
            "Plan": {"Node Type": "Seq Scan", "Total Cost": 10.0},
            "Planning Time": 0.5,
            "Execution Time": float(call_count * 5),
        }

    with patch("src.dataset.real_benchmark_executor._run_explain_analyze", side_effect=mock_explain_analyze):
        # Initial baseline (seq 1)
        base1 = manager.get_or_create_baseline("SELECT 1;", query_id="q_drift")

        # Later in campaign: request a fresh re-baseline block (seq 2)
        base2 = manager.request_fresh_baseline("SELECT 1;", query_id="q_drift", reason="scheduled_drift_check")

    assert base1["sequence_number"] == 1
    assert base2["sequence_number"] == 2
    assert base1["baseline_block_id"] != base2["baseline_block_id"]

    # Verify history has both blocks
    history = manager.get_baseline_history("q_drift")
    assert len(history) == 2
    assert history[0]["baseline_block_id"] == base1["baseline_block_id"]
    assert history[1]["baseline_block_id"] == base2["baseline_block_id"]

    # Verify neither was overwritten
    assert manager.get_baseline_by_id(base1["baseline_block_id"])["sequence_number"] == 1
    assert manager.get_baseline_by_id(base2["baseline_block_id"])["sequence_number"] == 2

    # Active baseline is now base2
    assert manager.get_active_baseline("q_drift")["baseline_block_id"] == base2["baseline_block_id"]


def test_candidate_explicit_reference_to_baseline_block():
    """
    Verify that candidate measurements explicitly reference the baseline block used
    and can be mapped back to it in the BaselineManager.
    """
    manager = BaselineManager(dbname="job_imdb")

    mock_baseline_plan = {
        "Plan": {"Node Type": "Seq Scan", "Relation Name": "company_type", "Total Cost": 100.0},
        "Planning Time": 1.0,
        "Execution Time": 50.0,
    }
    mock_candidate_plan = {
        "Plan": {"Node Type": "Index Scan", "Index Name": "exp_idx_ct_kind", "Total Cost": 10.0},
        "Planning Time": 0.8,
        "Execution Time": 15.0,
    }

    call_count = 0

    def mock_explain_analyze(cur, query, timeout_ms):
        nonlocal call_count
        call_count += 1
        # Calls 1..7: baseline benchmark
        if call_count <= 7:
            return mock_baseline_plan
        # Calls 8..14: candidate benchmark
        return mock_candidate_plan

    index_name = make_experimental_index_name("company_type", ["kind"])
    index_sql = build_create_index_sql(index_name, "company_type", ["kind"])

    with patch("src.dataset.real_benchmark_executor._run_explain_analyze", side_effect=mock_explain_analyze), \
         patch("src.dataset.real_index_benchmark.drop_experimental_index", return_value=True), \
         patch("src.dataset.real_index_benchmark.verify_index_absent", return_value=True), \
         patch("src.dataset.real_index_benchmark.get_connection"):

        result = benchmark_with_real_index(
            query="SELECT min(kind) FROM company_type WHERE kind = 'prod';",
            index_sql=index_sql,
            index_name=index_name,
            table_name="company_type",
            query_id="query_ct",
            baseline_manager=manager,
        )

    # Candidate explicitly references the baseline block used
    assert result["baseline_block_id"] is not None
    assert result["baseline_block_id"].startswith("base_query_ct_seq1_")
    assert result["baseline_sequence_number"] == 1
    assert result["baseline_created_at"] is not None
    assert result["T_baseline"] == 50.0

    # Baseline manager successfully links candidate to this baseline block
    linked_candidates = manager.get_candidates_for_baseline(result["baseline_block_id"])
    assert index_name in linked_candidates


def test_shared_baseline_preserves_explicit_identity():
    """
    Verify that passing a precomputed baseline into benchmark_with_real_index
    preserves its explicit baseline_block_id without re-measuring.
    """
    shared_baseline = {
        "baseline_block_id": "base_precomputed_block_999",
        "created_at": "2026-09-30T00:00:00Z",
        "sequence_number": 1,
        "status": "SUCCESS",
        "timed_out": False,
        "runtimes_ms": [25.0, 26.0, 25.5, 24.5, 25.0],
        "median_runtime_ms": 25.0,
        "T_baseline": 25.0,
        "planning_times_ms": [1.0, 1.1, 1.0, 0.9, 1.0],
        "median_planning_time_ms": 1.0,
        "plan": {"Plan": {"Node Type": "Seq Scan", "Total Cost": 80.0}},
    }

    mock_candidate_plan = {
        "Plan": {"Node Type": "Index Scan", "Index Name": "exp_idx_ct_kind", "Total Cost": 10.0},
        "Planning Time": 0.8,
        "Execution Time": 12.0,
    }

    index_name = make_experimental_index_name("company_type", ["kind"])
    index_sql = build_create_index_sql(index_name, "company_type", ["kind"])

    with patch("src.dataset.real_benchmark_executor._run_explain_analyze", return_value=mock_candidate_plan), \
         patch("src.dataset.real_index_benchmark.drop_experimental_index", return_value=True), \
         patch("src.dataset.real_index_benchmark.verify_index_absent", return_value=True), \
         patch("src.dataset.real_index_benchmark.get_connection"):

        result = benchmark_with_real_index(
            query="SELECT min(kind) FROM company_type WHERE kind = 'prod';",
            index_sql=index_sql,
            index_name=index_name,
            table_name="company_type",
            baseline_benchmark=shared_baseline,
        )

    # Precomputed baseline was used directly without modifying its identity
    assert result["baseline_block_id"] == "base_precomputed_block_999"
    assert result["T_baseline"] == 25.0
    assert result["baseline_median_runtime_ms"] == 25.0
    assert result["baseline_sequence_number"] == 1


def test_baseline_runtime_not_in_ml_features():
    """Verify that baseline runtime is NEVER leaked as an ML feature in extract_plan_features."""
    plan_with_runtime = [
        {
            "Plan": {
                "Node Type": "Seq Scan",
                "Relation Name": "title",
                "Startup Cost": 0.0,
                "Total Cost": 500.0,
                "Plan Rows": 1000,
                "Plan Width": 32,
            },
            "Planning Time": 1.5,
            "Execution Time": 75.0,
        }
    ]

    features = extract_plan_features(plan_with_runtime)

    # Verify structural plan features exist
    assert features["root_node_type"] == "Seq Scan"
    assert features["root_total_cost"] == 500.0

    # Verify NO runtime metrics leaked into features
    assert "Execution Time" not in features
    assert "Planning Time" not in features
    assert "T_baseline" not in features
    assert "baseline_runtime" not in features
    assert "median_runtime_ms" not in features


def main():
    print("=" * 70)
    print("RUNNING DECISION #5 BASELINE MEASUREMENT & DRIFT CONTROL TESTS")
    print("=" * 70)

    test_baseline_measurement_protocol()
    print("test_baseline_measurement_protocol: PASSED")

    test_baseline_median_and_raw_runtimes_preserved()
    print("test_baseline_median_and_raw_runtimes_preserved: PASSED")

    test_baseline_planning_time_separate()
    print("test_baseline_planning_time_separate: PASSED")

    test_baseline_identity_preserved()
    print("test_baseline_identity_preserved: PASSED")

    test_fresh_baseline_without_overwriting()
    print("test_fresh_baseline_without_overwriting: PASSED")

    test_candidate_explicit_reference_to_baseline_block()
    print("test_candidate_explicit_reference_to_baseline_block: PASSED")

    test_shared_baseline_preserves_explicit_identity()
    print("test_shared_baseline_preserves_explicit_identity: PASSED")

    test_baseline_runtime_not_in_ml_features()
    print("test_baseline_runtime_not_in_ml_features: PASSED")

    print("=" * 70)
    print("ALL DECISION #5 BASELINE TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    main()
