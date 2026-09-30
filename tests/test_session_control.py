"""
Tests for Decision #8: PostgreSQL JIT, GEQO, and Parallelism Control.

Verifies:
A. jit = off is applied at the benchmark session level.
B. max_parallel_workers_per_gather = 0 is applied at the session level.
C. geqo = off is applied at the session level.
D. No global/server configuration is modified.
E. Effective settings are captured in the experiment snapshot.
F. Settings are applied before EXPLAIN ANALYZE.
G. Decisions #3 through #7 remain intact.
"""

import math
from unittest.mock import MagicMock, call, patch

from src.dataset.real_benchmark_executor import (
    _run_explain_analyze,
    benchmark_query,
)
from src.dataset.real_index_benchmark import (
    benchmark_with_real_index,
)
from src.dataset.session_control import (
    LOCKED_SESSION_SETTINGS,
    apply_benchmark_session_settings,
    get_effective_session_settings,
    verify_plan_parallel_and_jit,
)
from src.dataset.statistics_manager import (
    get_statistics_control_snapshot,
)


def test_jit_off_applied_at_session_level():
    """
    Test A: jit = off is applied at the benchmark session level.
    """
    executed = []
    mock_cur = MagicMock()
    mock_cur.execute.side_effect = lambda sql, params=None: executed.append(str(sql).strip())
    mock_cur.fetchone.return_value = ("off",)

    settings = apply_benchmark_session_settings(mock_cur)

    assert "SET jit = off;" in executed
    assert settings["jit"] == "off"


def test_max_parallel_workers_per_gather_zero_at_session_level():
    """
    Test B: max_parallel_workers_per_gather = 0 is applied at the session level.
    """
    executed = []
    mock_cur = MagicMock()
    mock_cur.execute.side_effect = lambda sql, params=None: executed.append(str(sql).strip())
    mock_cur.fetchone.return_value = ("0",)

    settings = apply_benchmark_session_settings(mock_cur)

    assert "SET max_parallel_workers_per_gather = 0;" in executed
    assert settings["max_parallel_workers_per_gather"] == 0


def test_geqo_off_at_session_level():
    """
    Test C: geqo = off is applied at the session level.
    """
    executed = []
    mock_cur = MagicMock()
    mock_cur.execute.side_effect = lambda sql, params=None: executed.append(str(sql).strip())
    mock_cur.fetchone.return_value = ("off",)

    settings = apply_benchmark_session_settings(mock_cur)

    assert "SET geqo = off;" in executed
    assert settings["geqo"] == "off"


def test_no_global_or_server_config_modified():
    """
    Test D: No global/server configuration is modified.
    Only session-level SET statements are executed.
    """
    executed = []
    mock_cur = MagicMock()
    mock_cur.execute.side_effect = lambda sql, params=None: executed.append(str(sql).strip())
    mock_cur.fetchone.return_value = ("off",)

    apply_benchmark_session_settings(mock_cur)

    for stmt in executed:
        upper_stmt = stmt.upper()
        assert "ALTER SYSTEM" not in upper_stmt, f"Unexpected ALTER SYSTEM: {stmt}"
        assert "SET GLOBAL" not in upper_stmt, f"Unexpected SET GLOBAL: {stmt}"
        assert "POSTGRESQL.CONF" not in upper_stmt, f"Unexpected config change: {stmt}"


def test_effective_settings_captured_in_experiment_snapshot():
    """
    Test E: Effective settings are captured in the experiment snapshot:
    - jit
    - max_parallel_workers_per_gather
    - geqo
    """
    mock_cur = MagicMock()
    mock_cur.fetchone.side_effect = [
        ("PostgreSQL 18.6 on x86_64-windows",),  # version()
        ("job_imdb",),                          # current_database()
        ("100",),                               # default_statistics_target
        ("on",),                                # autovacuum
        ("on",),                                # server jit
        ("2",),                                 # server max_parallel_workers_per_gather
        ("on",),                                # server geqo
        ("off",),                               # session jit
        ("0",),                                 # session max_parallel_workers_per_gather
        ("off",),                               # session geqo
    ]
    mock_cur.fetchall.return_value = [("title", None, 1000.0, 10, 5)]

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.__enter__.return_value = mock_conn

    with patch("src.dataset.statistics_manager.get_connection", return_value=mock_conn):
        snap = get_statistics_control_snapshot(dbname="job_imdb")

        assert snap["jit"] == "off"
        assert snap["max_parallel_workers_per_gather"] == 0
        assert snap["geqo"] == "off"
        assert snap["session_settings"]["jit"] == "off"
        assert snap["session_settings"]["max_parallel_workers_per_gather"] == 0
        assert snap["session_settings"]["geqo"] == "off"
        assert snap["server_defaults"]["jit"] == "on"
        assert snap["server_defaults"]["max_parallel_workers_per_gather"] == 2
        assert snap["server_defaults"]["geqo"] == "on"


def test_settings_applied_before_explain_analyze():
    """
    Test F: Settings are applied before EXPLAIN ANALYZE execution.
    """
    call_order = []
    mock_cur = MagicMock()

    def record_execute(sql, params=None):
        sql_str = str(sql).strip()
        if "SET jit" in sql_str:
            call_order.append("SET_JIT")
        elif "SET max_parallel_workers_per_gather" in sql_str:
            call_order.append("SET_PARALLEL")
        elif "SET geqo" in sql_str:
            call_order.append("SET_GEQO")
        elif "EXPLAIN" in sql_str:
            call_order.append("EXPLAIN")

    mock_cur.execute.side_effect = record_execute
    mock_cur.fetchone.return_value = ([{
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "title",
            "Plan Rows": 10,
            "Total Cost": 5.0,
        },
        "Execution Time": 10.5,
        "Planning Time": 0.8,
    }],)

    res = _run_explain_analyze(mock_cur, "SELECT * FROM title;", 5000)

    # Verify that all SET commands occurred BEFORE EXPLAIN
    explain_idx = call_order.index("EXPLAIN")
    jit_idx = call_order.index("SET_JIT")
    parallel_idx = call_order.index("SET_PARALLEL")
    geqo_idx = call_order.index("SET_GEQO")

    assert jit_idx < explain_idx, "JIT was not set before EXPLAIN"
    assert parallel_idx < explain_idx, "Parallelism was not set before EXPLAIN"
    assert geqo_idx < explain_idx, "GEQO was not set before EXPLAIN"


def test_decisions_3_through_7_remain_intact():
    """
    Test G: Decisions #3 through #7 remain intact:
    - Decision #3: EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON)
    - Decision #4: 2 warmups + 5 repetitions, median as primary runtime
    - Decision #5: baseline_block_id, T_baseline
    - Decision #6: dynamic timeout limit, censoring metadata
    - Decision #7: statistics_frozen = True, run_analyze = False
    - Decision #8: session settings preserved in output
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
        "session_settings": {
            "jit": "off",
            "max_parallel_workers_per_gather": 0,
            "geqo": "off",
        },
        "jit": "off",
        "max_parallel_workers_per_gather": 0,
        "geqo": "off",
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

        # Decisions #3 & #4
        assert res["repetitions"] == 5
        assert res["warmups"] == 2
        assert res["median_runtime_ms"] == 50.0
        assert len(res["runtimes_ms"]) == 5
        assert res["median_planning_time_ms"] == 1.5

        # Decision #5
        assert res["baseline_block_id"] == "base_drift_block_1"
        assert res["T_baseline"] == 100.0

        # Decision #6
        assert res["timeout_limit_ms"] == 30000.0
        assert res["label_is_censored"] is False
        assert res["target_type"] == "observed"
        assert math.isclose(res["target"], 0.683, rel_tol=1e-3)

        # Decision #7
        assert res["statistics_frozen"] is True
        assert res["run_analyze"] is False

        # Decision #8
        assert res["jit"] == "off"
        assert res["max_parallel_workers_per_gather"] == 0
        assert res["geqo"] == "off"
        assert res["session_settings"]["jit"] == "off"
        assert res["session_settings"]["max_parallel_workers_per_gather"] == 0
        assert res["session_settings"]["geqo"] == "off"


def main():
    print("=" * 70)
    print("RUNNING DECISION #8 TESTS (TESTS A THROUGH G)")
    print("=" * 70)

    test_jit_off_applied_at_session_level()
    print("Test A: test_jit_off_applied_at_session_level: PASSED")

    test_max_parallel_workers_per_gather_zero_at_session_level()
    print("Test B: test_max_parallel_workers_per_gather_zero_at_session_level: PASSED")

    test_geqo_off_at_session_level()
    print("Test C: test_geqo_off_at_session_level: PASSED")

    test_no_global_or_server_config_modified()
    print("Test D: test_no_global_or_server_config_modified: PASSED")

    test_effective_settings_captured_in_experiment_snapshot()
    print("Test E: test_effective_settings_captured_in_experiment_snapshot: PASSED")

    test_settings_applied_before_explain_analyze()
    print("Test F: test_settings_applied_before_explain_analyze: PASSED")

    test_decisions_3_through_7_remain_intact()
    print("Test G: test_decisions_3_through_7_remain_intact: PASSED")

    print("=" * 70)
    print("ALL DECISION #8 TESTS A THROUGH G COMPLETED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    main()
