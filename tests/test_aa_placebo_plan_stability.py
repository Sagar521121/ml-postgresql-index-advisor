"""
Decision #9 Test Suite:
A/A Control, Irrelevant-Index Placebo, and Plan Stability Monitoring.

Verifies:
A. A/A uses 2 warmups + 5 measured per block.
B. A/A stores all five raw measurements for both blocks.
C. A/A uses median runtime.
D. A/A log-ratio uses epsilon = 1.0 ms.
E. Signed and absolute A/A log-ratios are correct.
F. Multiple A/A blocks are supported.
G. Empirical p90/p95 are descriptive statistics only.
H. Placebo follows CREATE → warmup → measure → DROP.
I. Placebo cleanup is guaranteed.
J. Placebo observations are marked as control observations.
K. Plan signatures are deterministic for identical structural plans.
L. Runtime/timestamp changes do not change the structural signature.
M. Structural plan changes are detected.
N. Existing Decisions #3 through #8 tests still pass.
"""

import math
import statistics
from unittest.mock import MagicMock, call, patch
import pytest

from src.dataset.aa_control import (
    DEFAULT_AA_EPSILON_MS,
    calculate_aa_log_ratio,
    calculate_dispersion_statistics,
    run_aa_comparison,
    run_aa_suite,
)
from src.dataset.placebo_control import (
    extract_query_predicates_and_joins_columns,
    run_placebo_benchmark,
    select_irrelevant_index_candidate,
)
from src.dataset.plan_stability import (
    compare_plan_signatures,
    extract_structural_plan,
    generate_plan_hash,
    generate_plan_signature,
)
from src.dataset.real_benchmark_executor import (
    DEFAULT_REPETITIONS,
    DEFAULT_WARMUPS,
    benchmark_query,
)


# =======================================================================
# Test A: A/A uses 2 warmups + 5 measured per block
# =======================================================================
def test_test_a_aa_uses_two_warmups_five_measured():
    """Verify that A/A executes exactly 2 warmups and 5 measured runs per block."""
    mock_block_result = {
        "status": "SUCCESS",
        "timed_out": False,
        "error_message": None,
        "runtimes_ms": [10.0, 10.5, 11.0, 11.5, 12.0],
        "median_runtime_ms": 11.0,
        "min_runtime_ms": 10.0,
        "max_runtime_ms": 12.0,
        "mean_runtime_ms": 11.0,
        "planning_times_ms": [0.5, 0.5, 0.5, 0.5, 0.5],
        "planning_time_ms": 0.5,
        "median_planning_time_ms": 0.5,
        "repetitions": DEFAULT_REPETITIONS,
        "warmups": DEFAULT_WARMUPS,
        "plan": {"Node Type": "Seq Scan", "Relation Name": "title"},
        "plan_signature": ("sig",),
        "plan_hash": "hash123",
    }

    with patch("src.dataset.aa_control.benchmark_query", return_value=mock_block_result) as mock_bench:
        obs = run_aa_comparison("SELECT 1;", "test_q1")

        assert mock_bench.call_count == 2
        # Verify both calls had warmups=2 and repetitions=5
        for c in mock_bench.call_args_list:
            assert c.kwargs["warmups"] == 2
            assert c.kwargs["repetitions"] == 5

        assert obs["block_a"]["warmups"] == 2
        assert obs["block_a"]["repetitions"] == 5
        assert obs["block_b"]["warmups"] == 2
        assert obs["block_b"]["repetitions"] == 5


# =======================================================================
# Test B: A/A stores all five raw measurements for both blocks
# =======================================================================
def test_test_b_aa_stores_all_five_raw_measurements():
    """Verify that all five raw execution measurements are preserved for both blocks."""
    runtimes_a = [12.1, 11.8, 12.5, 12.0, 11.9]
    runtimes_b = [13.0, 12.8, 13.5, 13.1, 13.2]

    def mock_bench(query, repetitions, warmups, timeout_ms, dbname):
        nonlocal call_count
        call_count += 1
        runtimes = runtimes_a if call_count == 1 else runtimes_b
        return {
            "status": "SUCCESS",
            "timed_out": False,
            "error_message": None,
            "runtimes_ms": runtimes,
            "median_runtime_ms": statistics.median(runtimes),
            "planning_times_ms": [0.4] * 5,
            "planning_time_ms": 0.4,
            "median_planning_time_ms": 0.4,
            "repetitions": repetitions,
            "warmups": warmups,
            "plan": {"Node Type": "Seq Scan"},
            "plan_signature": (),
            "plan_hash": "abc",
        }

    call_count = 0
    with patch("src.dataset.aa_control.benchmark_query", side_effect=mock_bench):
        obs = run_aa_comparison("SELECT 1;", "test_q_raw")

        assert obs["block_a"]["runtimes_ms"] == runtimes_a
        assert len(obs["block_a"]["runtimes_ms"]) == 5
        assert obs["block_b"]["runtimes_ms"] == runtimes_b
        assert len(obs["block_b"]["runtimes_ms"]) == 5


# =======================================================================
# Test C: A/A uses median runtime
# =======================================================================
def test_test_c_aa_uses_median_runtime():
    """Verify that block runtimes T_A and T_B are strictly the medians of raw measurements."""
    # Asymmetric distributions where median != mean
    runtimes_a = [10.0, 10.2, 10.5, 50.0, 60.0]  # median: 10.5, mean: 28.14
    runtimes_b = [20.0, 21.0, 22.0, 100.0, 120.0]  # median: 22.0, mean: 56.6

    call_count = 0
    def mock_bench(query, repetitions, warmups, timeout_ms, dbname):
        nonlocal call_count
        call_count += 1
        r = runtimes_a if call_count == 1 else runtimes_b
        return {
            "status": "SUCCESS",
            "timed_out": False,
            "error_message": None,
            "runtimes_ms": r,
            "median_runtime_ms": statistics.median(r),
            "mean_runtime_ms": statistics.mean(r),
            "planning_times_ms": [0.3] * 5,
            "planning_time_ms": 0.3,
            "median_planning_time_ms": 0.3,
            "repetitions": repetitions,
            "warmups": warmups,
            "plan": {"Node Type": "Seq Scan"},
            "plan_signature": (),
            "plan_hash": "abc",
        }

    with patch("src.dataset.aa_control.benchmark_query", side_effect=mock_bench):
        obs = run_aa_comparison("SELECT 1;", "test_q_med")

        assert obs["t_a"] == 10.5
        assert obs["t_a"] != statistics.mean(runtimes_a)
        assert obs["t_b"] == 22.0
        assert obs["t_b"] != statistics.mean(runtimes_b)


# =======================================================================
# Test D: A/A log-ratio uses epsilon = 1.0 ms
# =======================================================================
def test_test_d_aa_log_ratio_uses_epsilon_one_ms():
    """Verify that log ratio uses epsilon = 1.0 ms: log((T_A + 1.0) / (T_B + 1.0))."""
    # Test zero runtime
    signed, absolute = calculate_aa_log_ratio(0.0, 0.0, epsilon_ms=1.0)
    assert signed == 0.0
    assert absolute == 0.0

    # Test arbitrary runtimes
    t_a = 9.0
    t_b = 4.0
    # (9.0 + 1.0) / (4.0 + 1.0) = 10.0 / 5.0 = 2.0
    expected_signed = math.log(2.0)
    signed, absolute = calculate_aa_log_ratio(t_a, t_b, epsilon_ms=1.0)
    assert math.isclose(signed, expected_signed, rel_tol=1e-9)
    assert math.isclose(absolute, expected_signed, rel_tol=1e-9)

    # Verify constant
    assert DEFAULT_AA_EPSILON_MS == 1.0


# =======================================================================
# Test E: Signed and absolute A/A log-ratios are correct
# =======================================================================
def test_test_e_signed_and_absolute_log_ratios_are_correct():
    """Verify both signed and absolute log ratios for both T_A > T_B and T_A < T_B."""
    # Case 1: T_A > T_B (positive signed log-ratio)
    t_a = 120.0
    t_b = 100.0
    expected = math.log(121.0 / 101.0)  # ~ +0.18067
    signed, absolute = calculate_aa_log_ratio(t_a, t_b, epsilon_ms=1.0)
    assert signed > 0
    assert math.isclose(signed, expected, rel_tol=1e-7)
    assert math.isclose(absolute, expected, rel_tol=1e-7)

    # Case 2: T_A < T_B (negative signed log-ratio)
    t_a = 100.0
    t_b = 120.0
    expected_signed = math.log(101.0 / 121.0)  # ~ -0.18067
    expected_abs = abs(expected_signed)
    signed, absolute = calculate_aa_log_ratio(t_a, t_b, epsilon_ms=1.0)
    assert signed < 0
    assert math.isclose(signed, expected_signed, rel_tol=1e-7)
    assert math.isclose(absolute, expected_abs, rel_tol=1e-7)


# =======================================================================
# Test F: Multiple A/A blocks are supported
# =======================================================================
def test_test_f_multiple_aa_blocks_supported():
    """Verify that multiple A/A blocks/queries can be evaluated systematically."""
    queries = {
        "q1": "SELECT 1;",
        "q2": "SELECT 2;",
        "q3": "SELECT 3;",
    }

    def mock_bench(query, repetitions, warmups, timeout_ms, dbname):
        return {
            "status": "SUCCESS",
            "timed_out": False,
            "error_message": None,
            "runtimes_ms": [10.0] * 5,
            "median_runtime_ms": 10.0,
            "planning_times_ms": [0.1] * 5,
            "planning_time_ms": 0.1,
            "median_planning_time_ms": 0.1,
            "repetitions": repetitions,
            "warmups": warmups,
            "plan": {"Node Type": "Result"},
            "plan_signature": (("Node Type", "Result"),),
            "plan_hash": "res_hash",
        }

    with patch("src.dataset.aa_control.benchmark_query", side_effect=mock_bench):
        suite_res = run_aa_suite(queries)

        assert suite_res["total_count"] == 3
        assert suite_res["successful_count"] == 3
        assert len(suite_res["observations"]) == 3
        assert all(o["control_type"] == "aa_control" for o in suite_res["observations"])
        assert "dispersion_statistics" in suite_res


# =======================================================================
# Test G: Empirical p90/p95 are descriptive statistics only
# =======================================================================
def test_test_g_empirical_dispersion_statistics_descriptive_only():
    """Verify dispersion statistics are descriptive empirical percentiles, NOT confidence intervals."""
    # 20 observations
    noise_vals = [0.01 * i for i in range(1, 21)]  # 0.01 to 0.20
    stats = calculate_dispersion_statistics(noise_vals)

    assert stats["count"] == 20
    assert stats["is_descriptive_reference_only"] is True
    assert "NOT confidence intervals" in stats["statistical_meaning"]
    assert stats["median"] is not None
    assert stats["p90"] is not None
    assert stats["p95"] is not None
    assert stats["max"] == 0.20
    assert stats["min"] == 0.01
    assert stats["p90"] <= stats["p95"] <= stats["max"]


# =======================================================================
# Test H: Placebo follows CREATE → warmup → measure → DROP
# =======================================================================
def test_test_h_placebo_follows_create_warmup_measure_drop():
    """Verify exact operational sequence: CREATE INDEX -> warmup -> measured -> DROP INDEX."""
    call_log = []

    mock_baseline = {
        "baseline_block_id": "base_mock",
        "T_baseline": 50.0,
        "median_runtime_ms": 50.0,
        "status": "SUCCESS",
        "timed_out": False,
        "runtimes_ms": [50.0] * 5,
        "planning_times_ms": [1.0] * 5,
        "plan": {"Node Type": "Seq Scan", "Relation Name": "company_name"},
    }

    mock_bench_result = {
        "status": "SUCCESS",
        "timed_out": False,
        "error_message": None,
        "runtimes_ms": [51.0, 50.5, 49.8, 50.2, 51.1],
        "median_runtime_ms": 50.5,
        "planning_times_ms": [1.0] * 5,
        "planning_time_ms": 1.0,
        "median_planning_time_ms": 1.0,
        "repetitions": 5,
        "warmups": 2,
        "plan": {"Node Type": "Seq Scan", "Relation Name": "company_name"},
        "plan_signature": ("sig",),
        "plan_hash": "hash_company",
    }

    with patch("src.dataset.real_index_benchmark.get_connection") as mock_conn_func, \
         patch("src.dataset.real_index_benchmark.benchmark_query", side_effect=lambda **k: (call_log.append("benchmark_query"), mock_bench_result)[1]) as mock_bench, \
         patch("src.dataset.real_index_benchmark.verify_index_absent", return_value=True):

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_conn_func.return_value.__enter__.return_value = mock_conn

        def fake_execute(sql, *args):
            clean_sql = str(sql).strip()
            if "CREATE INDEX" in clean_sql:
                call_log.append("CREATE INDEX")
            elif "DROP INDEX" in clean_sql:
                call_log.append("DROP INDEX")

        mock_cur.execute.side_effect = fake_execute

        res = run_placebo_benchmark(
            query="SELECT min(name) FROM company_name WHERE id = 1;",
            query_id="placebo_test",
            placebo_candidate={"table": "company_name", "columns": ["name_pcode_nf"], "index_type": "btree"},
            baseline_benchmark=mock_baseline,
        )

        # Operational sequence must be CREATE INDEX -> benchmark_query (warmup + measure) -> DROP INDEX
        assert call_log == ["CREATE INDEX", "benchmark_query", "DROP INDEX"]
        assert res["execution_status"] == "SUCCESS"
        assert res["cleanup_status"] is True


# =======================================================================
# Test I: Placebo cleanup is guaranteed
# =======================================================================
def test_test_i_placebo_cleanup_guaranteed():
    """Verify that DROP INDEX is unconditionally invoked even if benchmark raises an error."""
    drop_called = False

    def fake_drop(index_name, dbname):
        nonlocal drop_called
        drop_called = True
        return True

    mock_baseline = {
        "baseline_block_id": "base_mock",
        "T_baseline": 20.0,
        "status": "SUCCESS",
        "median_runtime_ms": 20.0,
        "plan": {"Node Type": "Seq Scan"},
    }

    with patch("src.dataset.real_index_benchmark.get_connection"), \
         patch("src.dataset.real_index_benchmark.benchmark_query", side_effect=RuntimeError("DB Crashed")), \
         patch("src.dataset.real_index_benchmark.drop_experimental_index", side_effect=fake_drop), \
         patch("src.dataset.real_index_benchmark.verify_index_absent", return_value=True):

        res = run_placebo_benchmark(
            query="SELECT 1;",
            query_id="placebo_fail_test",
            placebo_candidate={"table": "company_name", "columns": ["name_pcode_nf"], "index_type": "btree"},
            baseline_benchmark=mock_baseline,
        )

        assert drop_called is True
        assert res["cleanup_status"] is True


# =======================================================================
# Test J: Placebo observations are marked as control observations
# =======================================================================
def test_test_j_placebo_observations_marked_as_control():
    """Verify placebo records have explicit control markers and all 9 required fields."""
    mock_baseline = {
        "baseline_block_id": "base_mock",
        "T_baseline": 30.0,
        "status": "SUCCESS",
        "median_runtime_ms": 30.0,
        "runtimes_ms": [30.0] * 5,
        "planning_times_ms": [0.5] * 5,
        "plan": {"Node Type": "Seq Scan"},
    }

    mock_bench_result = {
        "status": "SUCCESS",
        "timed_out": False,
        "error_message": None,
        "runtimes_ms": [30.2, 30.1, 29.9, 30.3, 30.0],
        "median_runtime_ms": 30.1,
        "planning_times_ms": [0.5] * 5,
        "planning_time_ms": 0.5,
        "median_planning_time_ms": 0.5,
        "repetitions": 5,
        "warmups": 2,
        "plan": {"Node Type": "Seq Scan"},
        "plan_signature": ("sig",),
        "plan_hash": "hash_placebo",
    }

    with patch("src.dataset.real_index_benchmark.get_connection"), \
         patch("src.dataset.real_index_benchmark.benchmark_query", return_value=mock_bench_result), \
         patch("src.dataset.real_index_benchmark.drop_experimental_index", return_value=True), \
         patch("src.dataset.real_index_benchmark.verify_index_absent", return_value=True):

        res = run_placebo_benchmark(
            query="SELECT 1;",
            query_id="q_placebo_mark",
            placebo_candidate={"table": "title", "columns": ["phonetic_code"], "index_type": "btree"},
            baseline_benchmark=mock_baseline,
        )

        # Control markers
        assert res["is_placebo"] is True
        assert res["is_control"] is True
        assert res["control_type"] == "irrelevant_index_placebo"
        assert res["candidate_type"] == "placebo"
        assert res["for_ml_training"] is False

        # All 9 required fields
        assert res["query_id"] == "q_placebo_mark"
        assert res["placebo_index_definition"]["table"] == "title"
        assert res["placebo_index_definition"]["columns"] == ["phonetic_code"]
        assert res["creation_success"] is True
        assert res["baseline_runtime"] == 30.0
        assert res["placebo_runtime"] == 30.1
        assert res["raw_runtimes"] == [30.2, 30.1, 29.9, 30.3, 30.0]
        assert res["planning_times"] == [0.5] * 5
        assert res["execution_status"] == "SUCCESS"
        assert res["cleanup_status"] is True

        # Measured placebo effect is recorded
        assert res["placebo_effect_signed_log_ratio"] is not None
        assert res["placebo_effect_abs_log_ratio"] is not None


# =======================================================================
# Test K: Plan signatures are deterministic for identical structural plans
# =======================================================================
def test_test_k_plan_signatures_deterministic_for_identical_plans():
    """Verify that identical structural plans produce identical signatures and hashes."""
    plan_a = {
        "Plan": {
            "Node Type": "Hash Join",
            "Join Type": "Inner",
            "Hash Cond": "(t.id = mc.movie_id)",
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "title",
                    "Alias": "t",
                    "Filter": "(production_year > 2000)",
                },
                {
                    "Node Type": "Hash",
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Relation Name": "movie_companies",
                            "Alias": "mc",
                        }
                    ],
                },
            ],
        }
    }

    plan_b = {
        "Plan": {
            "Node Type": "Hash Join",
            "Join Type": "Inner",
            "Hash Cond": "(t.id = mc.movie_id)",
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "title",
                    "Alias": "t",
                    "Filter": "(production_year > 2000)",
                },
                {
                    "Node Type": "Hash",
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Relation Name": "movie_companies",
                            "Alias": "mc",
                        }
                    ],
                },
            ],
        }
    }

    sig_a = generate_plan_signature(plan_a)
    sig_b = generate_plan_signature(plan_b)
    assert sig_a == sig_b

    hash_a = generate_plan_hash(plan_a)
    hash_b = generate_plan_hash(plan_b)
    assert hash_a == hash_b
    assert isinstance(hash_a, str) and len(hash_a) == 64  # SHA-256


# =======================================================================
# Test L: Runtime/timestamp changes do not change structural signature
# =======================================================================
def test_test_l_runtime_and_timestamp_changes_do_not_alter_signature():
    """Verify that runtime, buffer, row count, and cost fluctuations do not alter structural signature."""
    plan_run_1 = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "title",
            "Alias": "t",
            "Actual Rows": 100.0,
            "Actual Loops": 1,
            "Actual Startup Time": 0.05,
            "Actual Total Time": 12.34,
            "Shared Hit Blocks": 120,
            "Shared Read Blocks": 45,
            "Startup Cost": 0.0,
            "Total Cost": 500.0,
            "Plan Rows": 95,
        },
        "Execution Time": 12.34,
        "Planning Time": 0.45,
        "Planning": {"Shared Hit Blocks": 10},
    }

    plan_run_2 = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "title",
            "Alias": "t",
            "Actual Rows": 120.0,  # changed!
            "Actual Loops": 2,     # changed!
            "Actual Startup Time": 0.08, # changed!
            "Actual Total Time": 25.67,  # changed!
            "Shared Hit Blocks": 300,    # changed!
            "Shared Read Blocks": 0,     # changed!
            "Startup Cost": 10.0,        # changed!
            "Total Cost": 650.0,         # changed!
            "Plan Rows": 110,            # changed!
        },
        "Execution Time": 25.67,  # changed!
        "Planning Time": 1.12,    # changed!
        "Planning": {"Shared Hit Blocks": 25},
    }

    sig_1 = generate_plan_signature(plan_run_1)
    sig_2 = generate_plan_signature(plan_run_2)
    assert sig_1 == sig_2

    hash_1 = generate_plan_hash(plan_run_1)
    hash_2 = generate_plan_hash(plan_run_2)
    assert hash_1 == hash_2

    comparison = compare_plan_signatures(plan_run_1, plan_run_2)
    assert comparison["is_identical"] is True
    assert comparison["plan_changed"] is False
    assert comparison["plan_change_event"] is False


# =======================================================================
# Test M: Structural plan changes are detected
# =======================================================================
def test_test_m_structural_plan_changes_detected():
    """Verify that changes in node type, join topology, or index usage trigger a plan change event."""
    plan_seq = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "title",
            "Alias": "t",
        }
    }

    plan_idx = {
        "Plan": {
            "Node Type": "Index Scan",
            "Relation Name": "title",
            "Alias": "t",
            "Index Name": "title_pkey",
        }
    }

    sig_seq = generate_plan_signature(plan_seq)
    sig_idx = generate_plan_signature(plan_idx)
    assert sig_seq != sig_idx

    hash_seq = generate_plan_hash(plan_seq)
    hash_idx = generate_plan_hash(plan_idx)
    assert hash_seq != hash_idx

    comparison = compare_plan_signatures(plan_seq, plan_idx)
    assert comparison["is_identical"] is False
    assert comparison["plan_changed"] is True
    assert comparison["plan_change_event"] is True
