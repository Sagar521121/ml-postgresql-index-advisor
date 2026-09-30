"""
Tests for Decision #12: Full Benchmark Execution / Data Collection Protocol
Including fixes for:
1. Baseline API bug
2. Cache bias asymmetry (Baseline interspersed)
3. A/A and Placebo Controls
4. DDL timeouts
"""
import pytest
from unittest.mock import MagicMock, call, patch

from src.dataset.runner import run_benchmark_collection, generate_placebo_candidate
from src.dataset.dataset_builder import DatasetBuilder
from src.dataset.real_index_benchmark import benchmark_with_real_index

def test_14_failure_stops_safely_on_cleanup_failure():
    """14. failure stops safely on cleanup failure."""
    with patch("src.dataset.runner.benchmark_with_real_index") as mock_real, \
         patch("src.dataset.runner.evaluate_candidate") as mock_eval, \
         patch("src.dataset.runner.BaselineManager") as mock_baseline, \
         patch("src.dataset.runner.generate_candidates") as mock_gen:

        mock_gen.return_value = [{"table": "t1", "columns": ["c1"], "index_type": "btree"}]
        valid_plan = {"Plan": {"Node Type": "Seq Scan"}}
        mock_bm_inst = mock_baseline.return_value
        mock_bm_inst.request_fresh_baseline.return_value = {"status": "SUCCESS", "plan": valid_plan, "baseline_block_id": "b1"}
        mock_eval.return_value = {"plan": valid_plan, "hypothetical_index_name": "hypo1"}

        mock_real.return_value = {
            "status": "CLEANUP_ERROR",
            "cleanup_verified": False,
            "error_message": "Drop failed",
            "is_aa_control": False,
            "is_placebo": False,
        }

        queries = {"1a": "SELECT 1;"}
        with pytest.raises(RuntimeError, match="Cleanup failed during full benchmark"):
            run_benchmark_collection(queries, pilot=True, checkpoint_path=None)

def test_16_pilot_mode_filters_candidates():
    """16. pilot mode does not silently launch all 658 candidates."""
    with patch("src.dataset.runner.benchmark_with_real_index") as mock_real, \
         patch("src.dataset.runner.evaluate_candidate") as mock_eval, \
         patch("src.dataset.runner.BaselineManager") as mock_baseline, \
         patch("src.dataset.runner.generate_candidates") as mock_gen:

        queries = {f"q{i}": "SELECT 1;" for i in range(100)}
        mock_gen.return_value = [
            {"table": "t", "columns": [f"c{j}"], "index_type": "btree"} for j in range(10)
        ]
        valid_plan = {"Plan": {"Node Type": "Seq Scan"}}
        mock_bm_inst = mock_baseline.return_value
        mock_bm_inst.request_fresh_baseline.return_value = {"status": "SUCCESS", "plan": valid_plan, "baseline_block_id": "b1", "median_runtime_ms": 100.0}
        mock_eval.return_value = {"plan": valid_plan, "hypothetical_index_name": "hypo"}
        mock_real.return_value = {
            "status": "SUCCESS",
            "cleanup_verified": True,
            "T_baseline": 100.0,
            "actual_runtime_ms": 50.0,
            "timeout_limit_ms": 30000.0,
        }

        builder = run_benchmark_collection(queries, pilot=True, pilot_max_pairs=20, checkpoint_path=None)
        # 20 pairs total allowed. With candidates + controls, it filters the top-level items down to exactly 20.
        assert len(builder.rows) + len(builder.rejected) == 20

def test_measurement_ordering_and_cache_bias():
    """
    Ensure the runner requests a fresh baseline immediately before evaluating a candidate
    to mitigate cache bias. Also verifies correct A/A and Placebo scheduling.
    """
    with patch("src.dataset.runner.benchmark_with_real_index") as mock_real, \
         patch("src.dataset.runner.evaluate_candidate") as mock_eval, \
         patch("src.dataset.runner.BaselineManager") as mock_baseline, \
         patch("src.dataset.runner.generate_candidates") as mock_gen:

        mock_gen.return_value = [{"table": "t", "columns": ["c"], "index_type": "btree"}]
        valid_plan = {"Plan": {"Node Type": "Seq Scan"}}
        mock_bm_inst = mock_baseline.return_value
        mock_bm_inst.request_fresh_baseline.return_value = {"status": "SUCCESS", "plan": valid_plan, "baseline_block_id": "b1", "median_runtime_ms": 100.0}
        mock_eval.return_value = {"plan": valid_plan, "hypothetical_index_name": "hypo"}
        mock_real.return_value = {
            "status": "SUCCESS",
            "cleanup_verified": True,
            "T_baseline": 100.0,
            "actual_runtime_ms": 50.0,
            "timeout_limit_ms": 30000.0,
        }

        queries = {"1a": "SELECT 1 FROM title"}
        builder = run_benchmark_collection(queries, pilot=False, checkpoint_path=None)

        # We expect 3 iterations: candidate, aa_control, placebo
        assert len(builder.rows) == 1  # candidate
        assert len(builder.rejected) == 2 # aa_control and placebo

        # BaselineManager should have been called 4 times:
        # candidate baseline, aa_control baseline, aa_control evaluation, placebo baseline
        assert mock_bm_inst.request_fresh_baseline.call_count == 4

        # Verify A/A is recorded but rejected from ML
        aa_reject = next(r for r in builder.rejected if r["reason"] == "aa_control")
        assert aa_reject["candidate_id"] == "aa_control"
        assert "outcome" in aa_reject

        # Verify Placebo is recorded but rejected from ML
        placebo_reject = next(r for r in builder.rejected if r["reason"] == "placebo_control")
        assert "placebo_" in placebo_reject["candidate_id"]
        assert "outcome" in placebo_reject

def test_ddl_timeout_in_real_index_benchmark():
    """Ensure DDL sets statement_timeout appropriately."""
    with patch("src.dataset.real_index_benchmark.get_connection") as mock_conn, \
         patch("src.dataset.real_index_benchmark.benchmark_query") as mock_bq, \
         patch("src.dataset.real_index_benchmark.verify_index_absent") as mock_verify, \
         patch("src.dataset.real_index_benchmark.drop_experimental_index") as mock_drop, \
         patch("src.dataset.real_index_benchmark.BaselineManager") as mock_bm:

        mock_verify.return_value = True
        mock_cur = mock_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value

        # Simulate a DDL timeout exception during execution
        import psycopg
        mock_cur.execute.side_effect = psycopg.errors.QueryCanceled("canceling statement due to statement timeout")

        res = benchmark_with_real_index(
            query="SELECT 1",
            index_sql="CREATE INDEX exp_idx_test ON test(id)",
            index_name="exp_idx_test",
            table_name="test",
            query_id="1",
            timeout_ms=5000,
        )

        # Status should be BENCHMARK_ERROR because DDL failed
        assert res["status"] == "BENCHMARK_ERROR"
        assert "DDL Timeout" in res["error_message"]
        # Timeout limit was set correctly
        assert res["timeout_limit_ms"] == 5000.0
        # Cleanup was still attempted
        assert mock_verify.called

def test_baseline_api_bug():
    """Ensure we do not call get_baseline, and we properly pass warmups/repetitions."""
    from src.dataset.runner import run_benchmark_collection
    import inspect
    source = inspect.getsource(run_benchmark_collection)
    assert ".get_baseline(" not in source, "Must not use non-existent get_baseline method."
    assert "request_fresh_baseline(" in source, "Must use request_fresh_baseline API."
    assert "warmups=2" in source, "Must explicitly preserve 2 warmups"
    assert "repetitions=5" in source, "Must explicitly preserve 5 measured runs"
