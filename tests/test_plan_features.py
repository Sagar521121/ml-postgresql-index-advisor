"""
Decision #10 Test Suite:
Candidate / Plan Feature Extraction for ML-Based PostgreSQL Index Advisor.

Verifies:
- Simple Seq Scan plan
- Plan with Index Scan
- Nested join plan
- Bitmap Heap + Bitmap Index plan
- Missing node types returning zero
- Baseline/hypo delta calculations
- Unchanged plans
- Changed plans
- Structural signature comparison
- Leakage audit confirming forbidden fields are absent
- Deterministic output for identical plans
- Malformed plan handling
- Feature schema / allowlist test so newly added fields cannot silently introduce leakage
"""

import json
import numpy as np
import pytest

from src.features.plan_features import (
    FEATURE_SCHEMA,
    FORBIDDEN_LEAKAGE_KEYS,
    RELEVANT_NODE_TYPES,
    derive_candidate_usage_from_hypo_plan,
    extract_candidate_plan_features,
    extract_plan_feature_vector,
    extract_plan_features,
    extract_single_plan_features,
)


# =======================================================================
# Test 1: Feature Schema / Allowlist Test
# =======================================================================
def test_feature_schema_allowlist():
    """Verify that FEATURE_SCHEMA is an immutable allowlist containing exactly 74 features."""
    assert isinstance(FEATURE_SCHEMA, tuple)
    assert len(FEATURE_SCHEMA) == 74
    # All features must be unique
    assert len(set(FEATURE_SCHEMA)) == len(FEATURE_SCHEMA)

    # Allowlist audit: no forbidden leakage keywords in schema names
    for feat_name in FEATURE_SCHEMA:
        assert isinstance(feat_name, str)
        assert len(feat_name) > 0
        for forbidden in FORBIDDEN_LEAKAGE_KEYS:
            # Exact match or prefix/suffix leakage check
            assert feat_name != forbidden
            assert not feat_name.startswith(f"{forbidden}_")
            assert not feat_name.endswith(f"_{forbidden}")

    # Generate sample plan and assert extracted keys EXACTLY match FEATURE_SCHEMA
    sample_plan = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "title",
            "Startup Cost": 0.0,
            "Total Cost": 100.0,
            "Plan Rows": 500,
            "Plan Width": 32,
        }
    }
    extracted = extract_candidate_plan_features(sample_plan, sample_plan)
    assert tuple(extracted.keys()) == FEATURE_SCHEMA


# =======================================================================
# Test 2: Simple Seq Scan Plan
# =======================================================================
def test_simple_seq_scan_plan():
    """Verify scalar, node count, and depth extraction on a single-node Seq Scan plan."""
    base_plan = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "title",
            "Startup Cost": 0.0,
            "Total Cost": 500.0,
            "Plan Rows": 1000,
            "Plan Width": 32,
        }
    }
    hypo_plan = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "title",
            "Startup Cost": 0.0,
            "Total Cost": 450.0,
            "Plan Rows": 1000,
            "Plan Width": 32,
        }
    }

    feats = extract_candidate_plan_features(base_plan, hypo_plan)

    assert feats["baseline_total_cost"] == 500.0
    assert feats["hypo_total_cost"] == 450.0
    assert feats["total_cost_delta"] == -50.0

    assert feats["baseline_plan_depth"] == 1.0
    assert feats["hypo_plan_depth"] == 1.0
    assert feats["baseline_total_node_count"] == 1.0
    assert feats["hypo_total_node_count"] == 1.0

    assert feats["baseline_seq_scan_count"] == 1.0
    assert feats["hypo_seq_scan_count"] == 1.0
    assert feats["seq_scan_count_delta"] == 0.0


# =======================================================================
# Test 3: Plan with Index Scan
# =======================================================================
def test_plan_with_index_scan():
    """Verify that replacing a Seq Scan with an Index Scan adjusts counts, flags, and candidate usage."""
    base_plan = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "title",
            "Startup Cost": 0.0,
            "Total Cost": 1000.0,
            "Plan Rows": 5000,
            "Plan Width": 24,
        }
    }
    hypo_plan = {
        "Plan": {
            "Node Type": "Index Scan",
            "Relation Name": "title",
            "Index Name": "<15207>btree_title_id",
            "Startup Cost": 0.28,
            "Total Cost": 25.0,
            "Plan Rows": 1,
            "Plan Width": 24,
        }
    }

    feats = extract_candidate_plan_features(
        base_plan, hypo_plan, hypo_index_name="<15207>btree_title_id"
    )

    # Composition changes
    assert feats["baseline_seq_scan_count"] == 1.0
    assert feats["hypo_seq_scan_count"] == 0.0
    assert feats["seq_scan_count_delta"] == -1.0

    assert feats["baseline_index_scan_count"] == 0.0
    assert feats["hypo_index_scan_count"] == 1.0
    assert feats["index_scan_count_delta"] == 1.0

    # Structural changes
    assert feats["plan_changed"] == 1.0
    assert feats["scan_structure_changed"] == 1.0
    assert feats["join_structure_changed"] == 0.0

    # Candidate usage
    assert feats["candidate_used_in_hypo_plan"] == 1.0
    assert feats["candidate_unused_in_hypo_plan"] == 0.0


# =======================================================================
# Test 4: Nested Join Plan
# =======================================================================
def test_nested_join_plan():
    """Verify multi-level join hierarchy depth and node counts."""
    # Root: Aggregate (depth 1)
    #   Nested Loop (depth 2)
    #     Hash Join (depth 3)
    #       Seq Scan (mc) (depth 4)
    #       Hash (depth 4)
    #         Seq Scan (t) (depth 5)
    #     Index Scan (cn) (depth 3)
    nested_plan = {
        "Plan": {
            "Node Type": "Aggregate",
            "Startup Cost": 100.0,
            "Total Cost": 2500.0,
            "Plan Rows": 1,
            "Plan Width": 32,
            "Plans": [
                {
                    "Node Type": "Nested Loop",
                    "Join Type": "Inner",
                    "Startup Cost": 50.0,
                    "Total Cost": 2400.0,
                    "Plan Rows": 50,
                    "Plan Width": 32,
                    "Plans": [
                        {
                            "Node Type": "Hash Join",
                            "Join Type": "Inner",
                            "Startup Cost": 30.0,
                            "Total Cost": 1500.0,
                            "Plan Rows": 100,
                            "Plan Width": 24,
                            "Plans": [
                                {
                                    "Node Type": "Seq Scan",
                                    "Relation Name": "movie_companies",
                                    "Startup Cost": 0.0,
                                    "Total Cost": 600.0,
                                    "Plan Rows": 2000,
                                    "Plan Width": 12,
                                },
                                {
                                    "Node Type": "Hash",
                                    "Startup Cost": 20.0,
                                    "Total Cost": 20.0,
                                    "Plan Rows": 500,
                                    "Plan Width": 12,
                                    "Plans": [
                                        {
                                            "Node Type": "Seq Scan",
                                            "Relation Name": "title",
                                            "Startup Cost": 0.0,
                                            "Total Cost": 500.0,
                                            "Plan Rows": 500,
                                            "Plan Width": 12,
                                        }
                                    ],
                                },
                            ],
                        },
                        {
                            "Node Type": "Index Scan",
                            "Relation Name": "company_name",
                            "Index Name": "company_name_pkey",
                            "Startup Cost": 0.15,
                            "Total Cost": 8.0,
                            "Plan Rows": 1,
                            "Plan Width": 8,
                        },
                    ],
                }
            ],
        }
    }

    feats = extract_candidate_plan_features(nested_plan, nested_plan)

    # 1 Aggregate + 1 Nested Loop + 1 Hash Join + 2 Seq Scan + 1 Hash + 1 Index Scan = 7 nodes
    assert feats["baseline_total_node_count"] == 7.0
    assert feats["baseline_plan_depth"] == 5.0

    assert feats["baseline_aggregate_count"] == 1.0
    assert feats["baseline_nested_loop_count"] == 1.0
    assert feats["baseline_hash_join_count"] == 1.0
    assert feats["baseline_hash_count"] == 1.0
    assert feats["baseline_seq_scan_count"] == 2.0
    assert feats["baseline_index_scan_count"] == 1.0


# =======================================================================
# Test 5: Bitmap Heap + Bitmap Index Plan
# =======================================================================
def test_bitmap_heap_and_bitmap_index_plan():
    """Verify correct counting and depth for Bitmap Heap Scan and Bitmap Index Scan."""
    plan = {
        "Plan": {
            "Node Type": "Bitmap Heap Scan",
            "Relation Name": "orders",
            "Startup Cost": 4.5,
            "Total Cost": 250.0,
            "Plan Rows": 100,
            "Plan Width": 16,
            "Plans": [
                {
                    "Node Type": "Bitmap Index Scan",
                    "Index Name": "orders_customer_idx",
                    "Startup Cost": 0.0,
                    "Total Cost": 4.5,
                    "Plan Rows": 100,
                    "Plan Width": 0,
                }
            ],
        }
    }

    feats = extract_candidate_plan_features(plan, plan)

    assert feats["baseline_bitmap_heap_scan_count"] == 1.0
    assert feats["baseline_bitmap_index_scan_count"] == 1.0
    assert feats["baseline_seq_scan_count"] == 0.0
    assert feats["baseline_index_scan_count"] == 0.0
    assert feats["baseline_plan_depth"] == 2.0
    assert feats["baseline_total_node_count"] == 2.0


# =======================================================================
# Test 6: Missing Node Types Return Zero
# =======================================================================
def test_missing_node_types_return_zero():
    """Verify that node types absent from the plan produce strictly 0.0."""
    simple_plan = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Total Cost": 10.0,
            "Startup Cost": 0.0,
            "Plan Rows": 1,
            "Plan Width": 4,
        }
    }

    feats = extract_candidate_plan_features(simple_plan, simple_plan)

    absent_types = [
        "Incremental Sort",
        "Memoize",
        "Tid Scan",
        "Gather",
        "Gather Merge",
        "Materialize",
        "Merge Join",
    ]
    for nt in absent_types:
        clean = nt.lower().replace(" ", "_")
        assert feats[f"baseline_{clean}_count"] == 0.0
        assert feats[f"hypo_{clean}_count"] == 0.0
        assert feats[f"{clean}_count_delta"] == 0.0


# =======================================================================
# Test 7: Baseline / Hypo Delta Calculations
# =======================================================================
def test_baseline_hypo_delta_calculations():
    """Verify that all deltas strictly equal (hypo - baseline)."""
    base_plan = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Total Cost": 1000.0,
            "Startup Cost": 10.0,
            "Plan Rows": 5000.0,
            "Plan Width": 48.0,
        }
    }
    hypo_plan = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Total Cost": 250.0,
            "Startup Cost": 2.0,
            "Plan Rows": 50.0,
            "Plan Width": 40.0,
        }
    }

    feats = extract_candidate_plan_features(base_plan, hypo_plan)

    assert feats["total_cost_delta"] == 250.0 - 1000.0  # -750.0
    assert feats["startup_cost_delta"] == 2.0 - 10.0    # -8.0
    assert feats["plan_rows_delta"] == 50.0 - 5000.0    # -4950.0
    assert feats["plan_width_delta"] == 40.0 - 48.0     # -8.0
    assert feats["plan_depth_delta"] == 0.0
    assert feats["node_count_delta"] == 0.0


# =======================================================================
# Test 8: Unchanged Plans
# =======================================================================
def test_unchanged_plans():
    """Verify structural flags and deltas when plans are identical."""
    plan = {
        "Plan": {
            "Node Type": "Hash Join",
            "Join Type": "Inner",
            "Total Cost": 500.0,
            "Startup Cost": 10.0,
            "Plan Rows": 100.0,
            "Plan Width": 32.0,
            "Plans": [
                {
                    "Node Type": "Seq Scan",
                    "Relation Name": "title",
                    "Total Cost": 200.0,
                    "Startup Cost": 0.0,
                    "Plan Rows": 100.0,
                    "Plan Width": 16.0,
                },
                {
                    "Node Type": "Hash",
                    "Total Cost": 100.0,
                    "Startup Cost": 10.0,
                    "Plan Rows": 50.0,
                    "Plan Width": 16.0,
                    "Plans": [
                        {
                            "Node Type": "Seq Scan",
                            "Relation Name": "movie_companies",
                            "Total Cost": 100.0,
                            "Startup Cost": 0.0,
                            "Plan Rows": 50.0,
                            "Plan Width": 16.0,
                        }
                    ],
                },
            ],
        }
    }

    feats = extract_candidate_plan_features(plan, plan)

    assert feats["plan_changed"] == 0.0
    assert feats["scan_structure_changed"] == 0.0
    assert feats["join_structure_changed"] == 0.0
    assert feats["candidate_used_in_hypo_plan"] == 0.0
    assert feats["candidate_unused_in_hypo_plan"] == 1.0
    assert feats["total_cost_delta"] == 0.0
    assert feats["node_count_delta"] == 0.0


# =======================================================================
# Test 9: Changed Plans (Join Topology Shift)
# =======================================================================
def test_changed_plans_join_structure():
    """Verify that a shift from Hash Join to Nested Loop flags join_structure_changed and plan_changed."""
    base_plan = {
        "Plan": {
            "Node Type": "Hash Join",
            "Join Type": "Inner",
            "Total Cost": 500.0,
            "Startup Cost": 10.0,
            "Plan Rows": 100.0,
            "Plan Width": 32.0,
            "Plans": [
                {"Node Type": "Seq Scan", "Relation Name": "title"},
                {"Node Type": "Hash", "Plans": [{"Node Type": "Seq Scan", "Relation Name": "movie_companies"}]},
            ],
        }
    }
    hypo_plan = {
        "Plan": {
            "Node Type": "Nested Loop",
            "Join Type": "Inner",
            "Total Cost": 400.0,
            "Startup Cost": 0.0,
            "Plan Rows": 100.0,
            "Plan Width": 32.0,
            "Plans": [
                {"Node Type": "Seq Scan", "Relation Name": "title"},
                {"Node Type": "Seq Scan", "Relation Name": "movie_companies"},
            ],
        }
    }

    feats = extract_candidate_plan_features(base_plan, hypo_plan)

    assert feats["plan_changed"] == 1.0
    assert feats["join_structure_changed"] == 1.0


# =======================================================================
# Test 10: Structural Signature Comparison Methodology
# =======================================================================
def test_structural_signature_comparison_ignores_runtime_fluctuations():
    """Verify that runtime/timing fluctuations do not trigger plan_changed or scan/join changes."""
    base_plan = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "title",
            "Total Cost": 500.0,
            "Startup Cost": 0.0,
            "Plan Rows": 1000,
            "Plan Width": 32,
            "Actual Rows": 1000.0,
            "Actual Loops": 1,
            "Actual Total Time": 25.4,
        },
        "Execution Time": 25.4,
        "Planning Time": 0.5,
    }
    # Hypo plan has identical structure but perturbed runtime/cost stats
    hypo_plan = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "title",
            "Total Cost": 500.0,
            "Startup Cost": 0.0,
            "Plan Rows": 1000,
            "Plan Width": 32,
            "Actual Rows": 2000.0,  # changed!
            "Actual Loops": 2,     # changed!
            "Actual Total Time": 50.8,  # changed!
        },
        "Execution Time": 50.8,  # changed!
        "Planning Time": 1.2,    # changed!
    }

    feats = extract_candidate_plan_features(base_plan, hypo_plan)

    assert feats["plan_changed"] == 0.0
    assert feats["scan_structure_changed"] == 0.0
    assert feats["join_structure_changed"] == 0.0


# =======================================================================
# Test 11: Leakage Audit Confirming Forbidden Fields Are Absent
# =======================================================================
def test_leakage_audit_forbidden_fields_absent():
    """Audit that NO runtime, target, timeout, table, column, or candidate identity leaks."""
    base_plan = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "movie_companies",
            "Alias": "mc",
            "Startup Cost": 0.0,
            "Total Cost": 500.0,
            "Plan Rows": 1000,
            "Plan Width": 32,
            "Filter": "(note IS NOT NULL)",
        },
        "Execution Time": 75.3,
        "Planning Time": 1.2,
    }
    hypo_plan = {
        "Plan": {
            "Node Type": "Index Scan",
            "Relation Name": "movie_companies",
            "Alias": "mc",
            "Index Name": "<13824>btree_movie_companies_movie_id",
            "Startup Cost": 0.28,
            "Total Cost": 12.0,
            "Plan Rows": 2,
            "Plan Width": 32,
            "Index Cond": "(movie_id = 500)",
        },
        "Execution Time": 2.1,
        "Planning Time": 0.8,
    }

    feats = extract_candidate_plan_features(
        base_plan, hypo_plan, hypo_index_name="<13824>btree_movie_companies_movie_id"
    )

    # 1. Audit feature dictionary keys
    for k in feats.keys():
        for forbidden in FORBIDDEN_LEAKAGE_KEYS:
            assert k != forbidden, f"Forbidden key leaked: {k}"
            assert not k.startswith(f"{forbidden}_"), f"Forbidden prefix leaked in key: {k}"
            assert not k.endswith(f"_{forbidden}"), f"Forbidden suffix leaked in key: {k}"

    # 2. Audit feature dictionary values (MUST ALL BE NUMERIC)
    for k, v in feats.items():
        assert isinstance(v, (int, float)), f"Non-numeric value for {k}: {v!r}"
        assert not isinstance(v, bool), f"Boolean value for {k}: {v!r}"
        assert not np.isnan(v), f"NaN value for {k}"
        assert not np.isinf(v), f"Infinite value for {k}"

        # String representations must not leak names or runtimes
        val_str = str(v)
        assert "movie_companies" not in val_str
        assert "13824" not in val_str
        assert "75.3" not in val_str
        assert "2.1" not in val_str


# =======================================================================
# Test 12: Deterministic Output for Identical Plans
# =======================================================================
def test_deterministic_output_for_identical_plans():
    """Verify that repeated feature extractions produce 100% bit-for-bit identical results."""
    plan_a = {
        "Plan": {
            "Node Type": "Hash Join",
            "Total Cost": 800.0,
            "Startup Cost": 25.0,
            "Plan Rows": 300,
            "Plan Width": 48,
            "Plans": [
                {"Node Type": "Seq Scan", "Relation Name": "title", "Total Cost": 400.0, "Startup Cost": 0.0, "Plan Rows": 300, "Plan Width": 24},
                {"Node Type": "Hash", "Total Cost": 200.0, "Startup Cost": 20.0, "Plan Rows": 100, "Plan Width": 24, "Plans": [{"Node Type": "Seq Scan", "Relation Name": "movie_companies", "Total Cost": 200.0, "Startup Cost": 0.0, "Plan Rows": 100, "Plan Width": 24}]},
            ],
        }
    }
    plan_b = {
        "Plan": {
            "Node Type": "Nested Loop",
            "Total Cost": 300.0,
            "Startup Cost": 0.5,
            "Plan Rows": 50,
            "Plan Width": 48,
            "Plans": [
                {"Node Type": "Seq Scan", "Relation Name": "title", "Total Cost": 200.0, "Startup Cost": 0.0, "Plan Rows": 300, "Plan Width": 24},
                {"Node Type": "Index Scan", "Relation Name": "movie_companies", "Index Name": "<100>btree_mc_id", "Total Cost": 10.0, "Startup Cost": 0.5, "Plan Rows": 1, "Plan Width": 24},
            ],
        }
    }

    first_dict = extract_candidate_plan_features(plan_a, plan_b)
    first_vec = extract_plan_feature_vector(plan_a, plan_b)

    for _ in range(10):
        rep_dict = extract_candidate_plan_features(plan_a, plan_b)
        rep_vec = extract_plan_feature_vector(plan_a, plan_b)
        assert rep_dict == first_dict
        assert np.array_equal(rep_vec, first_vec)


# =======================================================================
# Test 13: Malformed Plan Handling
# =======================================================================
def test_malformed_plan_handling():
    """Verify that invalid/missing plans raise clear errors and are never silently converted."""
    valid_plan = {"Plan": {"Node Type": "Seq Scan", "Total Cost": 100.0}}

    # None inputs
    with pytest.raises(ValueError, match="Baseline plan cannot be None"):
        extract_candidate_plan_features(None, valid_plan)
    with pytest.raises(ValueError, match="HypoPG candidate plan cannot be None"):
        extract_candidate_plan_features(valid_plan, None)

    # Empty string
    with pytest.raises(ValueError, match="empty string"):
        extract_candidate_plan_features("", valid_plan)

    # Malformed JSON
    with pytest.raises(ValueError, match="Malformed EXPLAIN JSON"):
        extract_candidate_plan_features("{invalid_json", valid_plan)

    # Empty list
    with pytest.raises(ValueError, match="empty list"):
        extract_candidate_plan_features([], valid_plan)

    # Missing Plan / Node Type
    with pytest.raises(ValueError, match="missing 'Plan' or 'Node Type'"):
        extract_candidate_plan_features({"RandomKey": 123}, valid_plan)

    # Plan root not a dictionary
    with pytest.raises(ValueError, match="must be a dictionary"):
        extract_candidate_plan_features({"Plan": "not_a_dict"}, valid_plan)

    # Plan root missing Node Type
    with pytest.raises(ValueError, match="missing 'Node Type'"):
        extract_candidate_plan_features({"Plan": {"Total Cost": 100.0}}, valid_plan)


# =======================================================================
# Test 14: Extract Plan Feature Vector (NumPy Interface)
# =======================================================================
def test_extract_plan_feature_vector_numpy():
    """Verify extract_plan_feature_vector produces 1D float64 array matching FEATURE_SCHEMA length."""
    plan = {"Plan": {"Node Type": "Seq Scan", "Total Cost": 50.0, "Startup Cost": 0.0, "Plan Rows": 10, "Plan Width": 8}}
    vec = extract_plan_feature_vector(plan, plan)

    assert isinstance(vec, np.ndarray)
    assert vec.dtype == np.float64
    assert vec.ndim == 1
    assert len(vec) == len(FEATURE_SCHEMA)


# =======================================================================
# Test 15: Backward Compatibility Single Plan Extraction
# =======================================================================
def test_backward_compatibility_single_plan_extraction():
    """Verify that extract_plan_features(single_plan) returns legacy structure for existing tests."""
    plan = [
        {
            "Plan": {
                "Node Type": "Seq Scan",
                "Relation Name": "title",
                "Startup Cost": 0.0,
                "Total Cost": 500.0,
                "Plan Rows": 1000,
                "Plan Width": 32,
            }
        }
    ]

    res = extract_plan_features(plan)
    assert res["root_node_type"] == "Seq Scan"
    assert res["root_relation"] == "title"
    assert res["root_total_cost"] == 500.0
    assert res["root_plan_rows"] == 1000
    assert res["node_count"] == 1
    assert res["max_depth"] == 0
    assert isinstance(res["nodes"], list)
