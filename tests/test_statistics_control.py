"""
Tests for Decision #7: PostgreSQL Statistics & Maintenance Control.

Verifies:
A. The controlled statistics preparation step invokes VACUUM ANALYZE exactly once when preparing a benchmark database.
B. Candidate benchmarking does NOT automatically invoke ANALYZE.
C. Candidate benchmarking does NOT automatically invoke VACUUM ANALYZE.
D. default_statistics_target is captured.
E. PostgreSQL version and database identity are captured.
F. Statistics-control metadata is preserved with the benchmark configuration.
G. If per-table autovacuum/analyze settings are changed:
   - original values are captured
   - changes are explicit
   - restoration is possible
   - no global autovacuum setting is modified
H. Existing Decision #3, #4, #5, and #6 tests continue to pass.
"""

import math
from unittest.mock import MagicMock, call, patch

from src.dataset.real_index_benchmark import (
    benchmark_with_real_index,
    build_create_index_sql,
    make_experimental_index_name,
)
from src.dataset.statistics_manager import (
    apply_table_maintenance_policy,
    get_statistics_control_snapshot,
    get_table_reloptions,
    restore_table_maintenance_policy,
    run_controlled_vacuum_analyze,
)


def test_controlled_vacuum_analyze_once():
    """
    Test A: The controlled statistics preparation step invokes VACUUM ANALYZE
    exactly once when preparing a benchmark database (with autocommit=True).
    """
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.__enter__.return_value = mock_conn

    with patch("src.dataset.statistics_manager.get_connection", return_value=mock_conn):
        # Database-wide VACUUM ANALYZE
        res_db = run_controlled_vacuum_analyze(dbname="job_imdb")
        assert res_db["status"] == "SUCCESS"
        assert res_db["command"] == "VACUUM ANALYZE"
        assert res_db["scope"] == "database"
        assert mock_conn.autocommit is True
        mock_cursor.execute.assert_called_once_with("VACUUM ANALYZE")

        mock_cursor.reset_mock()

        # Scoped table VACUUM ANALYZE
        res_tbl = run_controlled_vacuum_analyze(dbname="job_imdb", table_name="title")
        assert res_tbl["status"] == "SUCCESS"
        assert res_tbl["command"] == 'VACUUM ANALYZE "title"'
        assert res_tbl["scope"] == "title"
        mock_cursor.execute.assert_called_once_with('VACUUM ANALYZE "title"')


def test_candidate_benchmarking_does_not_invoke_analyze():
    """
    Test B: Candidate benchmarking does NOT automatically invoke ANALYZE.
    By default, run_analyze is False and no statistics refreshes occur between candidates.
    """
    executed_statements = []
    mock_cur = MagicMock()
    mock_cur.execute.side_effect = lambda sql, params=None: executed_statements.append(str(sql))

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.__enter__.return_value = mock_conn

    fake_baseline = {
        "baseline_block_id": "base_test_001",
        "median_runtime_ms": 100.0,
        "T_baseline": 100.0,
        "status": "SUCCESS",
        "plan": {"Node Type": "Seq Scan", "Plan Rows": 100, "Total Cost": 50.0},
    }
    fake_benchmark_result = {
        "status": "SUCCESS",
        "error_message": None,
        "runtimes_ms": [80.0, 79.0, 81.0, 80.0, 80.0],
        "median_runtime_ms": 80.0,
        "plan": {"Node Type": "Index Scan", "Index Name": "exp_idx_test_title_id", "Plan Rows": 100, "Total Cost": 15.0},
    }

    with patch("src.dataset.real_index_benchmark.get_connection", return_value=mock_conn), \
         patch("src.dataset.real_index_benchmark.benchmark_query", return_value=fake_benchmark_result), \
         patch("src.dataset.real_index_benchmark.drop_experimental_index"), \
         patch("src.dataset.real_index_benchmark.verify_index_absent", return_value=True):

        res = benchmark_with_real_index(
            query="SELECT * FROM title WHERE id = 10;",
            index_sql="CREATE INDEX exp_idx_test_title_id ON title (id);",
            index_name="exp_idx_test_title_id",
            table_name="title",
            baseline_benchmark=fake_baseline,
        )

        assert res["status"] == "SUCCESS"
        assert res["run_analyze"] is False
        for stmt in executed_statements:
            assert "ANALYZE" not in stmt.strip().upper(), f"Unexpected ANALYZE found in: {stmt}"


def test_candidate_benchmarking_does_not_invoke_vacuum_analyze():
    """
    Test C: Candidate benchmarking does NOT automatically invoke VACUUM ANALYZE.
    """
    executed_statements = []
    mock_cur = MagicMock()
    mock_cur.execute.side_effect = lambda sql, params=None: executed_statements.append(str(sql))

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.__enter__.return_value = mock_conn

    fake_baseline = {
        "baseline_block_id": "base_test_002",
        "median_runtime_ms": 100.0,
        "T_baseline": 100.0,
        "status": "SUCCESS",
        "plan": {"Node Type": "Seq Scan", "Plan Rows": 100, "Total Cost": 50.0},
    }
    fake_benchmark_result = {
        "status": "SUCCESS",
        "error_message": None,
        "runtimes_ms": [80.0, 79.0, 81.0, 80.0, 80.0],
        "median_runtime_ms": 80.0,
        "plan": {"Node Type": "Index Scan", "Index Name": "exp_idx_test_title_id", "Plan Rows": 100, "Total Cost": 15.0},
    }

    with patch("src.dataset.real_index_benchmark.get_connection", return_value=mock_conn), \
         patch("src.dataset.real_index_benchmark.benchmark_query", return_value=fake_benchmark_result), \
         patch("src.dataset.real_index_benchmark.drop_experimental_index"), \
         patch("src.dataset.real_index_benchmark.verify_index_absent", return_value=True):

        res = benchmark_with_real_index(
            query="SELECT * FROM title WHERE id = 10;",
            index_sql="CREATE INDEX exp_idx_test_title_id ON title (id);",
            index_name="exp_idx_test_title_id",
            table_name="title",
            baseline_benchmark=fake_baseline,
        )

        assert res["status"] == "SUCCESS"
        assert res["statistics_frozen"] is True
        for stmt in executed_statements:
            assert "VACUUM" not in stmt.strip().upper(), f"Unexpected VACUUM found in: {stmt}"


def test_default_statistics_target_captured():
    """
    Test D: default_statistics_target is captured.
    """
    mock_cur = MagicMock()
    mock_cur.fetchone.side_effect = [
        ("PostgreSQL 18.6 on x86_64-windows",),
        ("job_imdb",),
        ("150",),  # Custom target
        ("on",),
    ]
    mock_cur.fetchall.return_value = [("title", None, 1000.0, 10, 5)]

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.__enter__.return_value = mock_conn

    with patch("src.dataset.statistics_manager.get_connection", return_value=mock_conn):
        snap = get_statistics_control_snapshot(dbname="job_imdb")
        assert "default_statistics_target" in snap
        assert snap["default_statistics_target"] == 150


def test_postgresql_version_and_database_identity_captured():
    """
    Test E: PostgreSQL version and database identity are captured.
    """
    mock_cur = MagicMock()
    mock_cur.fetchone.side_effect = [
        ("PostgreSQL 18.6 on x86_64-windows, compiled by msvc-19.44.35228, 64-bit",),
        ("job_imdb",),
        ("100",),
        ("on",),
    ]
    mock_cur.fetchall.return_value = [("title", None, 1000.0, 10, 5)]

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.__enter__.return_value = mock_conn

    with patch("src.dataset.statistics_manager.get_connection", return_value=mock_conn):
        snap = get_statistics_control_snapshot(dbname="job_imdb")
        assert snap["database_name"] == "job_imdb"
        assert "PostgreSQL 18.6" in snap["postgresql_version"]
        assert snap["statistics_frozen"] is True


def test_statistics_control_metadata_preserved_with_benchmark():
    """
    Test F: Statistics-control metadata is preserved with the benchmark configuration.
    """
    fake_snapshot = {
        "database_name": "job_imdb",
        "postgresql_version": "PostgreSQL 18.6",
        "default_statistics_target": 100,
        "autovacuum_global": "on",
        "statistics_frozen": True,
    }

    fake_baseline = {
        "baseline_block_id": "base_snap_001",
        "median_runtime_ms": 50.0,
        "T_baseline": 50.0,
        "status": "SUCCESS",
        "plan": {"Node Type": "Seq Scan", "Plan Rows": 10, "Total Cost": 10.0},
    }

    fake_benchmark = {
        "status": "SUCCESS",
        "error_message": None,
        "runtimes_ms": [20.0, 20.0, 20.0, 20.0, 20.0],
        "median_runtime_ms": 20.0,
        "plan": {"Node Type": "Index Scan", "Index Name": "exp_idx_test_col", "Plan Rows": 10, "Total Cost": 5.0},
    }

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = MagicMock()
    mock_conn.__enter__.return_value = mock_conn

    with patch("src.dataset.real_index_benchmark.get_connection", return_value=mock_conn), \
         patch("src.dataset.real_index_benchmark.benchmark_query", return_value=fake_benchmark), \
         patch("src.dataset.real_index_benchmark.drop_experimental_index"), \
         patch("src.dataset.real_index_benchmark.verify_index_absent", return_value=True):

        res = benchmark_with_real_index(
            query="SELECT * FROM title WHERE id = 1;",
            index_sql="CREATE INDEX exp_idx_test_col ON title (id);",
            index_name="exp_idx_test_col",
            table_name="title",
            baseline_benchmark=fake_baseline,
            statistics_snapshot=fake_snapshot,
        )

        assert res["statistics_frozen"] is True
        assert res["run_analyze"] is False
        assert res["statistics_snapshot"] == fake_snapshot
        assert res["statistics_snapshot"]["default_statistics_target"] == 100
        assert res["statistics_snapshot"]["database_name"] == "job_imdb"


def test_reversible_per_table_autovacuum_policy():
    """
    Test G: If per-table autovacuum/analyze settings are changed:
    - original values are captured
    - changes are explicit
    - restoration is possible
    - no global autovacuum setting is modified
    """
    mock_cur = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.__enter__.return_value = mock_conn

    initial_options = {
        "title": None,
        "cast_info": ["fillfactor=70"],
    }

    with patch("src.dataset.statistics_manager.get_connection", return_value=mock_conn), \
         patch("src.dataset.statistics_manager.get_table_reloptions", return_value=initial_options):

        # 1. Apply maintenance policy
        policy = apply_table_maintenance_policy(
            dbname="job_imdb",
            tables=["title", "cast_info"],
            disable_autovacuum=True,
        )

        assert policy["status"] == "APPLIED"
        assert policy["applied_setting"] == "autovacuum_enabled = false"
        assert policy["original_options"] == initial_options
        assert policy["changed_tables"] == ["cast_info", "title"]

        # Verify SQL statements issued
        applied_sqls = [call[0][0] for call in mock_cur.execute.call_args_list]
        assert 'ALTER TABLE "cast_info" SET (autovacuum_enabled = false);' in applied_sqls
        assert 'ALTER TABLE "title" SET (autovacuum_enabled = false);' in applied_sqls

        # Verify no ALTER SYSTEM or global config was touched
        for s in applied_sqls:
            assert "ALTER SYSTEM" not in s
            assert "SET GLOBAL" not in s

        # 2. Restore maintenance policy
        mock_cur.reset_mock()
        restore_res = restore_table_maintenance_policy(
            dbname="job_imdb",
            policy_record=policy,
        )

        assert restore_res["status"] == "RESTORED"
        assert restore_res["restored_tables"] == ["cast_info", "title"]

        restored_sqls = [call[0][0] for call in mock_cur.execute.call_args_list]
        # title had None, so RESET (autovacuum_enabled)
        assert 'ALTER TABLE "title" RESET (autovacuum_enabled);' in restored_sqls
        # cast_info had fillfactor=70, so restored with fillfactor=70
        assert 'ALTER TABLE "cast_info" SET (fillfactor=70);' in restored_sqls


def test_existing_decisions_3_4_5_6_continue_to_pass():
    """
    Test H: Existing Decision #3, #4, #5, and #6 tests continue to pass:
    - Decision #3: EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON)
    - Decision #4: 2 warmups + 5 repetitions, median as primary runtime
    - Decision #5: baseline_block_id, T_baseline
    - Decision #6: dynamic timeout limit, censoring metadata
    """
    fake_baseline = {
        "baseline_block_id": "base_drift_block_1",
        "median_runtime_ms": 100.0,
        "T_baseline": 100.0,
        "status": "SUCCESS",
        "runtimes_ms": [100.0, 101.0, 99.0, 100.0, 102.0],
        "planning_times_ms": [2.0, 2.0, 2.0, 2.0, 2.0],
        "median_planning_time_ms": 2.0,
        "plan": {"Node Type": "Seq Scan", "Plan Rows": 100, "Total Cost": 50.0},
    }

    fake_benchmark = {
        "status": "SUCCESS",
        "error_message": None,
        "runtimes_ms": [50.0, 52.0, 48.0, 51.0, 49.0],
        "median_runtime_ms": 50.0,
        "min_runtime_ms": 48.0,
        "max_runtime_ms": 52.0,
        "mean_runtime_ms": 50.0,
        "planning_times_ms": [1.5, 1.5, 1.5, 1.5, 1.5],
        "planning_time_ms": 1.5,
        "median_planning_time_ms": 1.5,
        "plan": {
            "Node Type": "Index Scan",
            "Index Name": "exp_idx_test_col",
            "Relation Name": "title",
            "Plan Rows": 100,
            "Total Cost": 10.0,
        },
    }

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = MagicMock()
    mock_conn.__enter__.return_value = mock_conn

    with patch("src.dataset.real_index_benchmark.get_connection", return_value=mock_conn), \
         patch("src.dataset.real_index_benchmark.benchmark_query", return_value=fake_benchmark), \
         patch("src.dataset.real_index_benchmark.drop_experimental_index"), \
         patch("src.dataset.real_index_benchmark.verify_index_absent", return_value=True):

        res = benchmark_with_real_index(
            query="SELECT * FROM title WHERE id = 1;",
            index_sql="CREATE INDEX exp_idx_test_col ON title (id);",
            index_name="exp_idx_test_col",
            table_name="title",
            baseline_benchmark=fake_baseline,
            repetitions=5,
            warmups=2,
        )

        # Decision #3 & #4
        assert res["repetitions"] == 5
        assert res["warmups"] == 2
        assert res["median_runtime_ms"] == 50.0
        assert len(res["runtimes_ms"]) == 5
        assert res["median_planning_time_ms"] == 1.5

        # Decision #5
        assert res["baseline_block_id"] == "base_drift_block_1"
        assert res["T_baseline"] == 100.0

        # Decision #6
        assert res["timeout_limit_ms"] == 30000.0  # max(30s, 1.5 * 100ms)
        assert res["label_is_censored"] is False
        assert res["target_type"] == "observed"
        assert math.isclose(res["target"], 0.683, rel_tol=1e-3)

        # Decision #7
        assert res["statistics_frozen"] is True
        assert res["run_analyze"] is False


def main():
    print("=" * 70)
    print("RUNNING DECISION #7 TESTS (TESTS A THROUGH H)")
    print("=" * 70)

    test_controlled_vacuum_analyze_once()
    print("Test A: test_controlled_vacuum_analyze_once: PASSED")

    test_candidate_benchmarking_does_not_invoke_analyze()
    print("Test B: test_candidate_benchmarking_does_not_invoke_analyze: PASSED")

    test_candidate_benchmarking_does_not_invoke_vacuum_analyze()
    print("Test C: test_candidate_benchmarking_does_not_invoke_vacuum_analyze: PASSED")

    test_default_statistics_target_captured()
    print("Test D: test_default_statistics_target_captured: PASSED")

    test_postgresql_version_and_database_identity_captured()
    print("Test E: test_postgresql_version_and_database_identity_captured: PASSED")

    test_statistics_control_metadata_preserved_with_benchmark()
    print("Test F: test_statistics_control_metadata_preserved_with_benchmark: PASSED")

    test_reversible_per_table_autovacuum_policy()
    print("Test G: test_reversible_per_table_autovacuum_policy: PASSED")

    test_existing_decisions_3_4_5_6_continue_to_pass()
    print("Test H: test_existing_decisions_3_4_5_6_continue_to_pass: PASSED")

    print("=" * 70)
    print("ALL DECISION #7 TESTS A THROUGH H COMPLETED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    main()
