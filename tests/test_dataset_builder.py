"""
Tests for Decision #11: Dataset Construction + Target Generation.

Test list (15 required):
  1.  exact 74-feature schema
  2.  successful target calculation
  3.  timeout target calculation
  4.  timeout actual runtime remains NULL
  5.  benchmark-error exclusion
  6.  A/A exclusion
  7.  placebo exclusion
  8.  duplicate query/candidate rejection
  9.  feature/metadata separation
  10. no forbidden leakage fields in ML matrix
  11. deterministic dataset construction
  12. correct handling of negative log-benefit
  13. epsilon exactly 1.0 ms
  14. timeout formula exactly max(30000, 1.5 * baseline)
  15. feature ordering matches FEATURE_SCHEMA
"""

import math
from typing import Any, Dict, List, Optional

import pytest

from src.dataset.dataset_builder import (
    DATASET_SCHEMA,
    EPSILON_MS,
    STATUS_BENCHMARK_ERROR,
    STATUS_SUCCESS,
    STATUS_TIMEOUT,
    DatasetBuilder,
    DatasetRow,
    _compute_target,
    audit_ml_matrix_for_leakage,
)
from src.dataset.timeout_policy import (
    DEFAULT_EPSILON_MS,
    calculate_dynamic_timeout_limit,
)
from src.features.plan_features import FEATURE_SCHEMA, FORBIDDEN_LEAKAGE_KEYS


# ── Shared plan fixtures ───────────────────────────────────────────────────────

def _make_plan(node_type: str = "Seq Scan", total_cost: float = 100.0) -> dict:
    """Return a minimal EXPLAIN JSON wrapper dict."""
    return {
        "Plan": {
            "Node Type": node_type,
            "Startup Cost": 0.0,
            "Total Cost": total_cost,
            "Plan Rows": 1000,
            "Plan Width": 32,
        },
        "Planning Time": 0.5,
        "Execution Time": 10.0,
    }


def _make_index_plan(total_cost: float = 50.0, hypo_name: str = "hypo_idx_123") -> dict:
    """Return a plan with an Index Scan using a hypothetical index."""
    return {
        "Plan": {
            "Node Type": "Index Scan",
            "Startup Cost": 0.0,
            "Total Cost": total_cost,
            "Plan Rows": 100,
            "Plan Width": 32,
            "Index Name": hypo_name,
        },
        "Planning Time": 0.3,
        "Execution Time": 5.0,
    }


def _make_outcome(
    status: str = STATUS_SUCCESS,
    t_baseline_ms: float = 200.0,
    actual_runtime_ms: Optional[float] = 100.0,
    timeout_limit_ms: Optional[float] = None,
    **extra,
) -> Dict[str, Any]:
    """Build a minimal benchmark_outcome dict."""
    return {
        "status": status,
        "T_baseline": t_baseline_ms,
        "actual_runtime_ms": actual_runtime_ms,
        "timeout_limit_ms": timeout_limit_ms or calculate_dynamic_timeout_limit(t_baseline_ms),
        "baseline_block_id": "block_01",
        "baseline_plan_hash": "abc123",
        "is_aa_control": False,
        "is_placebo": False,
        "is_control": False,
        **extra,
    }


def _make_candidate_def(
    table: str = "title",
    columns: str = "production_year",
    sql: str = "CREATE INDEX ON title(production_year)",
) -> Dict[str, Any]:
    return {"table": table, "columns": columns, "sql": sql}


def _make_builder_with_row(
    query_id: str = "q1",
    candidate_id: str = "c1",
    status: str = STATUS_SUCCESS,
    t_baseline_ms: float = 200.0,
    actual_runtime_ms: Optional[float] = 100.0,
    timeout_limit_ms: Optional[float] = None,
    **extra,
) -> DatasetBuilder:
    builder = DatasetBuilder()
    baseline_plan = _make_plan("Seq Scan", 100.0)
    hypo_plan = _make_index_plan(50.0)
    outcome = _make_outcome(status, t_baseline_ms, actual_runtime_ms, timeout_limit_ms, **extra)
    builder.add_observation(
        query_id=query_id,
        family_id="f1",
        candidate_id=candidate_id,
        candidate_def=_make_candidate_def(),
        baseline_plan=baseline_plan,
        hypo_plan=hypo_plan,
        hypo_index_name="hypo_idx_123",
        benchmark_outcome=outcome,
    )
    return builder


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1: Exact 74-feature schema
# ═══════════════════════════════════════════════════════════════════════════════

def test_01_exact_74_feature_schema():
    """Dataset builder must produce exactly the 74 FEATURE_SCHEMA features per row."""
    builder = _make_builder_with_row()
    assert len(builder.rows) == 1
    row = builder.rows[0]
    assert isinstance(row.features, dict)
    assert len(row.features) == 74, f"Expected 74 features, got {len(row.features)}"
    assert set(row.features.keys()) == set(FEATURE_SCHEMA)


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2: Successful target calculation
# ═══════════════════════════════════════════════════════════════════════════════

def test_02_successful_target_calculation():
    """
    SUCCESS target must equal log((T_baseline + 1.0) / (T_indexed + 1.0)).
    Epsilon must be exactly 1.0 ms.
    """
    t_baseline = 200.0
    t_indexed = 100.0
    expected_y = math.log((t_baseline + 1.0) / (t_indexed + 1.0))

    target, target_type, label_is_censored = _compute_target(
        t_baseline_ms=t_baseline,
        t_indexed_ms=t_indexed,
        status=STATUS_SUCCESS,
    )
    assert target is not None
    assert abs(target - expected_y) < 1e-12
    assert target_type == "observed"
    assert label_is_censored is False


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3: Timeout target calculation
# ═══════════════════════════════════════════════════════════════════════════════

def test_03_timeout_target_calculation():
    """
    TIMEOUT target must equal log((T_baseline + 1.0) / (T_limit + 1.0)).
    target_type must be 'bound_derived'. label_is_censored must be True.
    """
    t_baseline = 5000.0
    t_limit = max(30000.0, 1.5 * t_baseline)  # 30000.0 (min floor)
    expected_y = math.log((t_baseline + 1.0) / (t_limit + 1.0))

    target, target_type, label_is_censored = _compute_target(
        t_baseline_ms=t_baseline,
        t_indexed_ms=None,
        status=STATUS_TIMEOUT,
        timeout_limit_ms=t_limit,
    )
    assert target is not None
    assert abs(target - expected_y) < 1e-12
    assert target_type == "bound_derived"
    assert label_is_censored is True


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4: Timeout actual runtime remains NULL in metadata
# ═══════════════════════════════════════════════════════════════════════════════

def test_04_timeout_actual_runtime_is_null():
    """
    For TIMEOUT rows, actual_indexed_runtime_ms must be NULL in metadata.
    status must remain TIMEOUT. label_is_censored must be True.
    """
    builder = _make_builder_with_row(
        status=STATUS_TIMEOUT,
        t_baseline_ms=5000.0,
        actual_runtime_ms=None,  # timed out — no actual runtime
        timeout_limit_ms=30000.0,
    )
    assert len(builder.rows) == 1
    row = builder.rows[0]
    assert row.metadata["actual_indexed_runtime_ms"] is None
    assert row.metadata["status"] == STATUS_TIMEOUT
    assert row.metadata["label_is_censored"] is True
    assert row.metadata["target"] is not None  # bound-derived target exists


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5: Benchmark-error exclusion
# ═══════════════════════════════════════════════════════════════════════════════

def test_05_benchmark_error_exclusion():
    """
    Rows with status BENCHMARK_ERROR must be excluded from the dataset.
    No target should be computed. Rejection reason must be 'benchmark_error'.
    """
    builder = DatasetBuilder()
    outcome = {
        "status": STATUS_BENCHMARK_ERROR,
        "T_baseline": 200.0,
        "actual_runtime_ms": None,
        "timeout_limit_ms": 30000.0,
        "is_aa_control": False,
        "is_placebo": False,
        "is_control": False,
        "error_message": "Query execution failed",
    }
    builder.add_observation(
        query_id="q_error",
        family_id="f1",
        candidate_id="c1",
        candidate_def=_make_candidate_def(),
        baseline_plan=_make_plan(),
        hypo_plan=_make_index_plan(),
        benchmark_outcome=outcome,
    )
    assert len(builder.rows) == 0, "BENCHMARK_ERROR row should be excluded"
    assert len(builder.rejected) == 1
    assert builder.rejected[0]["reason"] == "benchmark_error"
    assert builder.rejected[0]["query_id"] == "q_error"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6: A/A control exclusion
# ═══════════════════════════════════════════════════════════════════════════════

def test_06_aa_control_exclusion():
    """
    A/A control observations must not enter ML training data.
    Rejection reason must be 'aa_control'.
    """
    builder = DatasetBuilder()
    outcome = _make_outcome()
    outcome["is_aa_control"] = True

    builder.add_observation(
        query_id="q_aa",
        family_id="f1",
        candidate_id="c_aa",
        candidate_def=_make_candidate_def(),
        baseline_plan=_make_plan(),
        hypo_plan=_make_index_plan(),
        benchmark_outcome=outcome,
    )
    assert len(builder.rows) == 0
    assert builder.rejected[0]["reason"] == "aa_control"


def test_06b_aa_control_type_exclusion():
    """A/A detection also works via control_type field."""
    builder = DatasetBuilder()
    outcome = _make_outcome()
    outcome["control_type"] = "aa_control"

    builder.add_observation(
        query_id="q_aa2",
        family_id="f1",
        candidate_id="c_aa2",
        candidate_def=_make_candidate_def(),
        baseline_plan=_make_plan(),
        hypo_plan=_make_index_plan(),
        benchmark_outcome=outcome,
    )
    assert len(builder.rows) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7: Placebo exclusion
# ═══════════════════════════════════════════════════════════════════════════════

def test_07_placebo_exclusion():
    """
    Placebo (irrelevant-index) observations must not enter ML training data.
    Rejection reason must be 'placebo_control'.
    """
    builder = DatasetBuilder()
    outcome = _make_outcome()
    outcome["is_placebo"] = True
    outcome["is_control"] = True

    builder.add_observation(
        query_id="q_placebo",
        family_id="f1",
        candidate_id="c_placebo",
        candidate_def=_make_candidate_def(),
        baseline_plan=_make_plan(),
        hypo_plan=_make_index_plan(),
        benchmark_outcome=outcome,
    )
    assert len(builder.rows) == 0
    assert builder.rejected[0]["reason"] == "placebo_control"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 8: Duplicate (query_id, candidate_id) rejection
# ═══════════════════════════════════════════════════════════════════════════════

def test_08_duplicate_pair_rejection():
    """
    Adding the same (query_id, candidate_id) twice must reject the second observation.
    The first observation must be retained.
    """
    builder = DatasetBuilder()

    for i in range(2):
        builder.add_observation(
            query_id="q_dup",
            family_id="f1",
            candidate_id="c_dup",
            candidate_def=_make_candidate_def(),
            baseline_plan=_make_plan(),
            hypo_plan=_make_index_plan(),
            benchmark_outcome=_make_outcome(),
        )

    assert len(builder.rows) == 1, "Duplicate pair must be rejected"
    assert len(builder.rejected) == 1
    assert builder.rejected[0]["reason"] == "duplicate_pair"


def test_08b_different_candidates_same_query_accepted():
    """Different candidates for the same query must all be accepted."""
    builder = DatasetBuilder()
    for i in range(3):
        builder.add_observation(
            query_id="q_multi",
            family_id="f1",
            candidate_id=f"c_{i}",
            candidate_def=_make_candidate_def(),
            baseline_plan=_make_plan(),
            hypo_plan=_make_index_plan(),
            benchmark_outcome=_make_outcome(),
        )
    assert len(builder.rows) == 3
    assert len(builder.rejected) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Test 9: Feature/metadata separation
# ═══════════════════════════════════════════════════════════════════════════════

def test_09_feature_metadata_separation():
    """
    Feature dict and metadata dict must be strictly disjoint.
    Feature keys must be exactly FEATURE_SCHEMA.
    Metadata must contain identifier and provenance fields.
    """
    builder = _make_builder_with_row()
    row = builder.rows[0]

    feature_keys = set(row.features.keys())
    metadata_keys = set(row.metadata.keys())

    # Strict disjointness
    intersection = feature_keys & metadata_keys
    assert len(intersection) == 0, f"Overlap between features and metadata: {intersection}"

    # Feature completeness
    assert feature_keys == set(FEATURE_SCHEMA)

    # Required metadata fields
    for required in ("query_id", "family_id", "candidate_id", "status", "target", "label_is_censored"):
        assert required in metadata_keys, f"Required metadata key missing: {required}"

    # Metadata must not contain ML leakage
    for k in FORBIDDEN_LEAKAGE_KEYS:
        # Metadata CAN hold some of these — only the ML feature matrix must be clean
        # But metadata must NOT hold FEATURE_SCHEMA keys
        assert k not in feature_keys, f"Forbidden key {k!r} found in features"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 10: No forbidden leakage fields in ML matrix
# ═══════════════════════════════════════════════════════════════════════════════

def test_10_no_leakage_in_ml_matrix():
    """
    The ML feature matrix (feature dicts only) must not contain any FORBIDDEN_LEAKAGE_KEYS
    or any keys outside FEATURE_SCHEMA.
    """
    # Add several rows with different statuses
    builder = DatasetBuilder()
    baseline = _make_plan()
    hypo = _make_index_plan()

    builder.add_observation(
        query_id="q1", family_id="f1", candidate_id="c1",
        candidate_def=_make_candidate_def(),
        baseline_plan=baseline, hypo_plan=hypo,
        benchmark_outcome=_make_outcome(STATUS_SUCCESS, 200.0, 100.0),
    )
    builder.add_observation(
        query_id="q2", family_id="f1", candidate_id="c2",
        candidate_def=_make_candidate_def(),
        baseline_plan=baseline, hypo_plan=hypo,
        benchmark_outcome=_make_outcome(STATUS_TIMEOUT, 5000.0, None, 30000.0),
    )

    ml_matrix = builder.ml_matrix_dicts()
    audit = audit_ml_matrix_for_leakage(ml_matrix)

    assert audit["passed"], (
        f"Leakage audit failed: {audit['violation_count']} violations\n"
        + "\n".join(str(v) for v in audit["violations"])
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 11: Deterministic dataset construction
# ═══════════════════════════════════════════════════════════════════════════════

def test_11_deterministic_dataset_construction():
    """
    Constructing the dataset twice from identical inputs must produce identical
    feature vectors and targets.
    """
    baseline = _make_plan("Seq Scan", 120.0)
    hypo = _make_index_plan(60.0)
    outcome = _make_outcome(STATUS_SUCCESS, 300.0, 150.0)

    def build():
        b = DatasetBuilder()
        b.add_observation(
            query_id="q_det", family_id="f1", candidate_id="c_det",
            candidate_def=_make_candidate_def(),
            baseline_plan=baseline, hypo_plan=hypo,
            benchmark_outcome=outcome,
        )
        return b.rows[0]

    row1 = build()
    row2 = build()

    assert row1.features == row2.features, "Feature vectors differ between runs"
    assert row1.metadata["target"] == row2.metadata["target"], "Targets differ between runs"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 12: Correct handling of negative log-benefit (slowdown)
# ═══════════════════════════════════════════════════════════════════════════════

def test_12_negative_log_benefit_slowdown():
    """
    When the indexed runtime is SLOWER than the baseline, the target must be negative.
    This represents a harmful index that the ML model should learn to avoid.
    """
    t_baseline = 100.0
    t_indexed = 200.0  # slower — index causes slowdown
    expected_y = math.log((t_baseline + 1.0) / (t_indexed + 1.0))

    assert expected_y < 0, "Slowdown target must be negative"

    target, target_type, label_is_censored = _compute_target(
        t_baseline_ms=t_baseline,
        t_indexed_ms=t_indexed,
        status=STATUS_SUCCESS,
    )
    assert target is not None
    assert target < 0
    assert abs(target - expected_y) < 1e-12
    assert label_is_censored is False


# ═══════════════════════════════════════════════════════════════════════════════
# Test 13: Epsilon exactly 1.0 ms
# ═══════════════════════════════════════════════════════════════════════════════

def test_13_epsilon_exactly_1ms():
    """
    Epsilon used in target computation must be exactly 1.0 ms (Decision #11 locked).
    Verify both the constant and the arithmetic.
    """
    assert EPSILON_MS == 1.0, f"EPSILON_MS must be 1.0 ms, got {EPSILON_MS}"
    assert DEFAULT_EPSILON_MS == 1.0, f"DEFAULT_EPSILON_MS must be 1.0 ms, got {DEFAULT_EPSILON_MS}"

    t_baseline = 0.0  # edge case: zero runtime
    t_indexed = 0.0
    # With epsilon=1: log(1/1) = 0
    target, _, _ = _compute_target(t_baseline_ms=t_baseline, t_indexed_ms=t_indexed, status=STATUS_SUCCESS)
    assert target is not None
    assert abs(target - 0.0) < 1e-12, f"log((0+1)/(0+1)) should be 0, got {target}"

    # Manually verify formula: log((100+1)/(50+1))
    t_b, t_i = 100.0, 50.0
    expected = math.log(101.0 / 51.0)
    target2, _, _ = _compute_target(t_b, t_i, STATUS_SUCCESS)
    assert abs(target2 - expected) < 1e-12


# ═══════════════════════════════════════════════════════════════════════════════
# Test 14: Timeout formula exactly max(30000, 1.5 * baseline)
# ═══════════════════════════════════════════════════════════════════════════════

def test_14_timeout_formula_max_30000_or_1_5x_baseline():
    """
    Timeout limit formula must be exactly max(30000 ms, 1.5 * T_baseline).
    Verify both branches:
      - When 1.5 * T_baseline < 30000 → T_limit = 30000
      - When 1.5 * T_baseline > 30000 → T_limit = 1.5 * T_baseline
    """
    # Case 1: small baseline → floor applies
    t_small = 5000.0  # 1.5 * 5000 = 7500 < 30000 → T_limit = 30000
    t_limit_small = calculate_dynamic_timeout_limit(t_small)
    assert t_limit_small == 30000.0, f"Expected 30000 ms floor, got {t_limit_small}"

    target_small, _, censored_small = _compute_target(
        t_baseline_ms=t_small,
        t_indexed_ms=None,
        status=STATUS_TIMEOUT,
        timeout_limit_ms=t_limit_small,
    )
    expected_small = math.log((t_small + 1.0) / (30000.0 + 1.0))
    assert abs(target_small - expected_small) < 1e-12
    assert censored_small is True

    # Case 2: large baseline → multiplier applies
    t_large = 50000.0  # 1.5 * 50000 = 75000 > 30000 → T_limit = 75000
    t_limit_large = calculate_dynamic_timeout_limit(t_large)
    assert t_limit_large == 75000.0, f"Expected 75000 ms, got {t_limit_large}"

    target_large, _, censored_large = _compute_target(
        t_baseline_ms=t_large,
        t_indexed_ms=None,
        status=STATUS_TIMEOUT,
        timeout_limit_ms=t_limit_large,
    )
    expected_large = math.log((t_large + 1.0) / (75000.0 + 1.0))
    assert abs(target_large - expected_large) < 1e-12
    assert censored_large is True

    # Case 3: exactly at threshold (20000 ms)
    t_at = 20000.0  # 1.5 * 20000 = 30000 → T_limit = 30000 (both are equal)
    t_limit_at = calculate_dynamic_timeout_limit(t_at)
    assert t_limit_at == 30000.0


# ═══════════════════════════════════════════════════════════════════════════════
# Test 15: Feature ordering matches FEATURE_SCHEMA
# ═══════════════════════════════════════════════════════════════════════════════

def test_15_feature_ordering_matches_schema():
    """
    The feature vector output must follow the exact FEATURE_SCHEMA ordering.
    When converting to a numpy array (or list), position i must correspond to
    FEATURE_SCHEMA[i].
    """
    from src.features.plan_features import extract_plan_feature_vector

    baseline = _make_plan("Seq Scan", 100.0)
    hypo = _make_index_plan(50.0)

    # Get ordered feature vector via the existing API
    feature_vector = extract_plan_feature_vector(baseline, hypo, "hypo_idx_123")
    assert len(feature_vector) == 74, f"Feature vector must have 74 elements, got {len(feature_vector)}"

    # Get the feature dict from the builder
    builder = _make_builder_with_row()
    row = builder.rows[0]

    # Build ordered list from dict using FEATURE_SCHEMA order
    ordered_from_dict = [row.features[k] for k in FEATURE_SCHEMA]

    assert len(ordered_from_dict) == 74

    # Confirm that iterating in FEATURE_SCHEMA order gives correct positions
    for i, key in enumerate(FEATURE_SCHEMA):
        assert key in row.features, f"Missing FEATURE_SCHEMA key at position {i}: {key}"

    # Confirm the numpy vector and the dict produce the same ordering
    import numpy as np
    dict_array = np.array(ordered_from_dict, dtype=np.float64)
    assert dict_array.shape == feature_vector.shape
    assert np.allclose(dict_array, feature_vector, atol=1e-8), (
        "Feature ordering mismatch between extract_plan_feature_vector and DatasetBuilder"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Additional validation tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_summary_counts_match_added_rows():
    """Summary counters must accurately reflect the rows added."""
    builder = DatasetBuilder()
    baseline = _make_plan()
    hypo = _make_index_plan()

    # Add 2 SUCCESS + 1 TIMEOUT + 1 BENCHMARK_ERROR + 1 DUPLICATE
    for i in range(2):
        builder.add_observation(
            query_id=f"q_success_{i}", family_id="f1", candidate_id=f"c_{i}",
            candidate_def=_make_candidate_def(),
            baseline_plan=baseline, hypo_plan=hypo,
            benchmark_outcome=_make_outcome(STATUS_SUCCESS, 200.0, 100.0),
        )
    builder.add_observation(
        query_id="q_timeout", family_id="f1", candidate_id="c_timeout",
        candidate_def=_make_candidate_def(),
        baseline_plan=baseline, hypo_plan=hypo,
        benchmark_outcome=_make_outcome(STATUS_TIMEOUT, 5000.0, None, 30000.0),
    )
    # BENCHMARK_ERROR — should be rejected
    builder.add_observation(
        query_id="q_err", family_id="f1", candidate_id="c_err",
        candidate_def=_make_candidate_def(),
        baseline_plan=baseline, hypo_plan=hypo,
        benchmark_outcome={
            "status": STATUS_BENCHMARK_ERROR, "T_baseline": 200.0,
            "actual_runtime_ms": None, "timeout_limit_ms": 30000.0,
            "is_aa_control": False, "is_placebo": False, "is_control": False,
        },
    )
    # Duplicate
    builder.add_observation(
        query_id="q_success_0", family_id="f1", candidate_id="c_0",
        candidate_def=_make_candidate_def(),
        baseline_plan=baseline, hypo_plan=hypo,
        benchmark_outcome=_make_outcome(STATUS_SUCCESS, 200.0, 100.0),
    )

    s = builder.summary()
    assert s["total_accepted"] == 3  # 2 SUCCESS + 1 TIMEOUT
    assert s["total_rejected"] == 2  # 1 BENCHMARK_ERROR + 1 duplicate
    assert s["status_counts"][STATUS_SUCCESS] == 2
    assert s["status_counts"][STATUS_TIMEOUT] == 1


def test_metadata_has_no_feature_schema_keys():
    """Metadata must not contain any key that is in FEATURE_SCHEMA."""
    builder = _make_builder_with_row()
    row = builder.rows[0]
    for k in FEATURE_SCHEMA:
        assert k not in row.metadata, f"FEATURE_SCHEMA key {k!r} must not be in metadata"


def test_flat_dict_has_all_expected_keys():
    """as_flat_dict must contain all feature keys + all metadata keys."""
    builder = _make_builder_with_row()
    row = builder.rows[0]
    flat = row.as_flat_dict()
    for k in FEATURE_SCHEMA:
        assert k in flat, f"Feature key {k!r} missing from flat dict"
    for k in row.metadata:
        assert k in flat, f"Metadata key {k!r} missing from flat dict"


def test_benchmark_error_target_is_none():
    """_compute_target for BENCHMARK_ERROR must return (None, None, False)."""
    target, target_type, censored = _compute_target(
        t_baseline_ms=200.0,
        t_indexed_ms=None,
        status=STATUS_BENCHMARK_ERROR,
    )
    assert target is None
    assert target_type is None
    assert censored is False


def test_timeout_target_is_always_negative():
    """
    The timeout target log((T_base+1)/(T_limit+1)) must always be negative
    since T_limit >= T_base.
    """
    for t_base in [100.0, 500.0, 5000.0, 25000.0, 100000.0]:
        t_limit = calculate_dynamic_timeout_limit(t_base)
        target, _, _ = _compute_target(t_base, None, STATUS_TIMEOUT, t_limit)
        assert target is not None
        assert target <= 0.0, f"Timeout target must be <= 0 for T_base={t_base}, T_limit={t_limit}"
