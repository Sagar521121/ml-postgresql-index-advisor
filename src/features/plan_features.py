"""
Decision #10: Candidate / Plan Feature Extraction for the ML-Based PostgreSQL
Query Performance & Index Advisor.

Converts:
1. baseline PostgreSQL EXPLAIN JSON plan
2. HypoPG candidate EXPLAIN JSON plan
3. their differences

into a deterministic, ML-ready numerical feature vector for XGBoost.

Feature Architecture:
A. Baseline plan scalar features (cost, rows, width, depth, node count)
B. HypoPG candidate plan scalar features (cost, rows, width, depth, node count)
C. Delta features (hypo - baseline for all scalar dimensions)
D. Plan-node composition (counts for 17 relevant PostgreSQL node types for baseline, hypo, delta)
E. Structural features (depths, plan_changed, scan_structure_changed, join_structure_changed,
   candidate_used_in_hypo_plan, candidate_unused_in_hypo_plan)

Strict Leakage Rules:
Forbidden fields are strictly barred from the feature schema:
- query_id, family_id
- table names, column names
- candidate index identity / name
- actual baseline runtime, actual candidate runtime
- target values
- timeout_limit, timeout status
- real-index plan information or post-execution observations
- timestamps
"""

from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union
import numpy as np

from src.dataset.plan_stability import (
    compare_plan_signatures,
    extract_structural_plan,
)
from src.dataset.real_benchmark_executor import parse_explain_json


RELEVANT_NODE_TYPES: Tuple[str, ...] = (
    "Seq Scan",
    "Index Scan",
    "Index Only Scan",
    "Bitmap Heap Scan",
    "Bitmap Index Scan",
    "Tid Scan",
    "Nested Loop",
    "Hash Join",
    "Merge Join",
    "Sort",
    "Incremental Sort",
    "Aggregate",
    "Hash",
    "Materialize",
    "Memoize",
    "Gather",
    "Gather Merge",
)

SCAN_NODE_TYPES: Set[str] = {
    "Seq Scan",
    "Index Scan",
    "Index Only Scan",
    "Bitmap Heap Scan",
    "Bitmap Index Scan",
    "Tid Scan",
    "Subquery Scan",
    "Function Scan",
    "Values Scan",
    "CTE Scan",
    "WorkTable Scan",
}

JOIN_NODE_TYPES: Set[str] = {
    "Nested Loop",
    "Hash Join",
    "Merge Join",
}


def _sanitize_node_type_name(node_type: str) -> str:
    """Convert PostgreSQL plan node type into standardized snake_case identifier."""
    return node_type.lower().replace(" ", "_")


# Explicit Feature Schema Allowlist Definition
BASELINE_SCALAR_FEATURES: Tuple[str, ...] = (
    "baseline_total_cost",
    "baseline_startup_cost",
    "baseline_plan_rows",
    "baseline_plan_width",
    "baseline_plan_depth",
    "baseline_total_node_count",
)

HYPO_SCALAR_FEATURES: Tuple[str, ...] = (
    "hypo_total_cost",
    "hypo_startup_cost",
    "hypo_plan_rows",
    "hypo_plan_width",
    "hypo_plan_depth",
    "hypo_total_node_count",
)

DELTA_SCALAR_FEATURES: Tuple[str, ...] = (
    "total_cost_delta",
    "startup_cost_delta",
    "plan_rows_delta",
    "plan_width_delta",
    "plan_depth_delta",
    "node_count_delta",
)

COMPOSITION_FEATURES: Tuple[str, ...] = tuple(
    name
    for node_type in RELEVANT_NODE_TYPES
    for name in (
        f"baseline_{_sanitize_node_type_name(node_type)}_count",
        f"hypo_{_sanitize_node_type_name(node_type)}_count",
        f"{_sanitize_node_type_name(node_type)}_count_delta",
    )
)

STRUCTURAL_FEATURES: Tuple[str, ...] = (
    "plan_changed",
    "scan_structure_changed",
    "join_structure_changed",
    "candidate_used_in_hypo_plan",
    "candidate_unused_in_hypo_plan",
)

FEATURE_SCHEMA: Tuple[str, ...] = (
    BASELINE_SCALAR_FEATURES
    + HYPO_SCALAR_FEATURES
    + DELTA_SCALAR_FEATURES
    + COMPOSITION_FEATURES
    + STRUCTURAL_FEATURES
)

FORBIDDEN_LEAKAGE_KEYS: Tuple[str, ...] = (
    "query_id",
    "family_id",
    "table_name",
    "table_names",
    "table",
    "column_name",
    "column_names",
    "column",
    "index_name",
    "candidate_name",
    "candidate_index",
    "candidate_identity",
    "actual_runtime",
    "actual_runtime_ms",
    "runtime",
    "baseline_runtime",
    "candidate_runtime",
    "median_runtime_ms",
    "target",
    "speedup_target",
    "y_timeout",
    "timeout_limit",
    "timeout_limit_ms",
    "timeout_status",
    "status",
    "timed_out",
    "label_is_censored",
    "target_is_censored",
    "real_candidate_used",
    "real_plan_changed",
    "real_used_indexes",
    "real_plan_classification",
    "timestamp",
    "created_at",
)


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convert numeric value to float safely; raise ValueError on malformed non-numeric values."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Malformed numeric plan property: {val!r}") from e


def _unwrap_and_validate_plan(raw_plan: Any, plan_role: str = "Plan") -> Dict[str, Any]:
    """
    Parse and validate a PostgreSQL EXPLAIN JSON plan.
    Ensures root is a valid dictionary containing required plan node properties.
    Raises ValueError with a clear message for malformed, missing, or empty plans.
    """
    if raw_plan is None:
        raise ValueError(f"{plan_role} cannot be None.")

    try:
        parsed = parse_explain_json(raw_plan)
    except ValueError as e:
        raise ValueError(f"Invalid {plan_role}: {e}") from e

    if not isinstance(parsed, dict):
        raise ValueError(f"Invalid {plan_role}: expected dict, got {type(parsed).__name__}.")

    if "Plan" in parsed:
        root = parsed["Plan"]
    elif "Node Type" in parsed:
        root = parsed
    else:
        raise ValueError(f"Invalid {plan_role}: missing 'Plan' or 'Node Type' key.")

    if not isinstance(root, dict):
        raise ValueError(f"Invalid {plan_role}: root 'Plan' must be a dictionary.")

    if "Node Type" not in root or not root["Node Type"]:
        raise ValueError(f"Invalid {plan_role}: root plan node missing 'Node Type'.")

    return root


def _traverse_plan_nodes(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Recursively collect all plan nodes in depth-first traversal order."""
    nodes = [node]
    for child in node.get("Plans", []):
        if isinstance(child, dict):
            nodes.extend(_traverse_plan_nodes(child))
    return nodes


def _compute_plan_depth(node: Dict[str, Any]) -> int:
    """Calculate the maximum depth of the execution plan tree (single node = 1)."""
    children = node.get("Plans", [])
    if not isinstance(children, list) or not children:
        return 1
    child_depths = [_compute_plan_depth(ch) for ch in children if isinstance(ch, dict)]
    return 1 + (max(child_depths) if child_depths else 0)


def _extract_scan_structure_signature(nodes: List[Dict[str, Any]]) -> Tuple:
    """
    Extract the structural signature of all scan operations in the plan tree.
    Captures node type, parent relationship, relation alias/name, index presence,
    scan direction, and filters.
    """
    sig = []
    for n in nodes:
        nt = n.get("Node Type")
        if nt in SCAN_NODE_TYPES:
            sig.append((
                nt,
                n.get("Parent Relationship"),
                n.get("Relation Name"),
                n.get("Alias"),
                n.get("Index Name"),
                n.get("Scan Direction"),
                n.get("Filter"),
                n.get("Index Cond"),
            ))
    return tuple(sig)


def _extract_join_structure_signature(nodes: List[Dict[str, Any]]) -> Tuple:
    """
    Extract the structural signature of all join operations in the plan tree.
    Captures join node type, join strategy, condition expressions, and inner uniqueness.
    """
    sig = []
    for n in nodes:
        nt = n.get("Node Type")
        if nt in JOIN_NODE_TYPES:
            sig.append((
                nt,
                n.get("Join Type"),
                n.get("Parent Relationship"),
                n.get("Inner Unique"),
                n.get("Hash Cond"),
                n.get("Merge Cond"),
                n.get("Join Filter"),
                n.get("Filter"),
            ))
    return tuple(sig)


def derive_candidate_usage_from_hypo_plan(
    hypo_root: Dict[str, Any],
    hypo_index_name: Optional[str] = None,
) -> Tuple[float, float]:
    """
    Derive strictly from the HypoPG plan whether the candidate index was used.
    Does NOT use any real-index execution or runtime data.

    Returns:
        (candidate_used_in_hypo_plan, candidate_unused_in_hypo_plan)
        as floats: (1.0, 0.0) if used, (0.0, 1.0) if not used.
    """
    hypo_nodes = _traverse_plan_nodes(hypo_root)
    used_indexes = [n.get("Index Name") for n in hypo_nodes if n.get("Index Name")]

    if hypo_index_name is not None:
        is_used = bool(hypo_index_name in used_indexes)
    else:
        # Check if any index name starts with HypoPG's universal '<oid>' naming pattern
        is_used = any(
            isinstance(idx, str) and idx.startswith("<") and ">" in idx
            for idx in used_indexes
        )

    if is_used:
        return (1.0, 0.0)
    else:
        return (0.0, 1.0)


def extract_candidate_plan_features(
    baseline_plan: Any,
    hypo_plan: Any,
    hypo_index_name: Optional[str] = None,
) -> Dict[str, float]:
    """
    Convert baseline plan and HypoPG candidate plan into an ML-ready numerical
    feature dictionary conforming strictly to FEATURE_SCHEMA.

    Feature Architecture:
    - Group A: Baseline scalar features (cost, rows, width, depth, node count)
    - Group B: HypoPG scalar features (cost, rows, width, depth, node count)
    - Group C: Delta features (hypo - baseline)
    - Group D: Plan-node composition (counts for 17 relevant node types)
    - Group E: Structural features (plan_changed, scan/join changes, candidate usage)

    Raises:
        ValueError: If either plan is None, malformed, empty, or missing required plan structures.
    """
    baseline_root = _unwrap_and_validate_plan(baseline_plan, plan_role="Baseline plan")
    hypo_root = _unwrap_and_validate_plan(hypo_plan, plan_role="HypoPG candidate plan")

    baseline_nodes = _traverse_plan_nodes(baseline_root)
    hypo_nodes = _traverse_plan_nodes(hypo_root)

    # A. Baseline plan features
    b_total_cost = _safe_float(baseline_root.get("Total Cost"))
    b_startup_cost = _safe_float(baseline_root.get("Startup Cost"))
    b_plan_rows = _safe_float(baseline_root.get("Plan Rows"))
    b_plan_width = _safe_float(baseline_root.get("Plan Width"))
    b_plan_depth = float(_compute_plan_depth(baseline_root))
    b_total_nodes = float(len(baseline_nodes))

    # B. HypoPG candidate plan features
    h_total_cost = _safe_float(hypo_root.get("Total Cost"))
    h_startup_cost = _safe_float(hypo_root.get("Startup Cost"))
    h_plan_rows = _safe_float(hypo_root.get("Plan Rows"))
    h_plan_width = _safe_float(hypo_root.get("Plan Width"))
    h_plan_depth = float(_compute_plan_depth(hypo_root))
    h_total_nodes = float(len(hypo_nodes))

    # C. Delta features (hypo - baseline)
    total_cost_delta = h_total_cost - b_total_cost
    startup_cost_delta = h_startup_cost - b_startup_cost
    plan_rows_delta = h_plan_rows - b_plan_rows
    plan_width_delta = h_plan_width - b_plan_width
    plan_depth_delta = h_plan_depth - b_plan_depth
    node_count_delta = h_total_nodes - b_total_nodes

    # D. Plan-node composition
    b_type_counts = Counter(n.get("Node Type") for n in baseline_nodes if n.get("Node Type"))
    h_type_counts = Counter(n.get("Node Type") for n in hypo_nodes if n.get("Node Type"))

    composition_dict: Dict[str, float] = {}
    for node_type in RELEVANT_NODE_TYPES:
        clean_name = _sanitize_node_type_name(node_type)
        b_count = float(b_type_counts.get(node_type, 0))
        h_count = float(h_type_counts.get(node_type, 0))
        composition_dict[f"baseline_{clean_name}_count"] = b_count
        composition_dict[f"hypo_{clean_name}_count"] = h_count
        composition_dict[f"{clean_name}_count_delta"] = h_count - b_count

    # E. Structural features
    # Use existing project plan-signature methodology for plan_changed
    comparison = compare_plan_signatures(baseline_root, hypo_root)
    plan_changed = 1.0 if comparison["plan_changed"] else 0.0

    # Scan and Join structural stability
    b_scan_sig = _extract_scan_structure_signature(baseline_nodes)
    h_scan_sig = _extract_scan_structure_signature(hypo_nodes)
    scan_structure_changed = 1.0 if b_scan_sig != h_scan_sig else 0.0

    b_join_sig = _extract_join_structure_signature(baseline_nodes)
    h_join_sig = _extract_join_structure_signature(hypo_nodes)
    join_structure_changed = 1.0 if b_join_sig != h_join_sig else 0.0

    # Candidate usage derived strictly from HypoPG plan
    cand_used, cand_unused = derive_candidate_usage_from_hypo_plan(
        hypo_root=hypo_root,
        hypo_index_name=hypo_index_name,
    )

    # Assemble complete feature vector in canonical FEATURE_SCHEMA order
    features: Dict[str, float] = {
        # Group A
        "baseline_total_cost": b_total_cost,
        "baseline_startup_cost": b_startup_cost,
        "baseline_plan_rows": b_plan_rows,
        "baseline_plan_width": b_plan_width,
        "baseline_plan_depth": b_plan_depth,
        "baseline_total_node_count": b_total_nodes,
        # Group B
        "hypo_total_cost": h_total_cost,
        "hypo_startup_cost": h_startup_cost,
        "hypo_plan_rows": h_plan_rows,
        "hypo_plan_width": h_plan_width,
        "hypo_plan_depth": h_plan_depth,
        "hypo_total_node_count": h_total_nodes,
        # Group C
        "total_cost_delta": total_cost_delta,
        "startup_cost_delta": startup_cost_delta,
        "plan_rows_delta": plan_rows_delta,
        "plan_width_delta": plan_width_delta,
        "plan_depth_delta": plan_depth_delta,
        "node_count_delta": node_count_delta,
    }

    # Group D
    features.update(composition_dict)

    # Group E
    features["plan_changed"] = plan_changed
    features["scan_structure_changed"] = scan_structure_changed
    features["join_structure_changed"] = join_structure_changed
    features["candidate_used_in_hypo_plan"] = cand_used
    features["candidate_unused_in_hypo_plan"] = cand_unused

    return features


def extract_plan_feature_vector(
    baseline_plan: Any,
    hypo_plan: Any,
    hypo_index_name: Optional[str] = None,
) -> np.ndarray:
    """
    Extract features as a 1D NumPy float64 array aligned with FEATURE_SCHEMA.
    """
    feat_dict = extract_candidate_plan_features(
        baseline_plan=baseline_plan,
        hypo_plan=hypo_plan,
        hypo_index_name=hypo_index_name,
    )
    return np.array([feat_dict[k] for k in FEATURE_SCHEMA], dtype=np.float64)


# ===========================================================================
# Backward Compatibility Section (Preserves existing tests / callers)
# ===========================================================================
def walk_plan(node: Dict[str, Any], depth: int = 0) -> List[Dict[str, Any]]:
    """Recursively walk through a PostgreSQL execution plan tree (legacy utility)."""
    features = []
    current = {
        "node_type": node.get("Node Type"),
        "relation": node.get("Relation Name"),
        "startup_cost": node.get("Startup Cost"),
        "total_cost": node.get("Total Cost"),
        "plan_rows": node.get("Plan Rows"),
        "plan_width": node.get("Plan Width"),
        "depth": depth,
    }
    features.append(current)

    for child in node.get("Plans", []):
        if isinstance(child, dict):
            features.extend(walk_plan(child, depth + 1))
    return features


def extract_single_plan_features(plan: Any) -> Dict[str, Any]:
    """Legacy single-plan feature extractor preserved for existing tests."""
    root = _unwrap_and_validate_plan(plan, plan_role="Plan")
    nodes = walk_plan(root)

    return {
        "root_node_type": root.get("Node Type"),
        "root_relation": root.get("Relation Name"),
        "root_startup_cost": root.get("Startup Cost"),
        "root_total_cost": root.get("Total Cost"),
        "root_plan_rows": root.get("Plan Rows"),
        "root_plan_width": root.get("Plan Width"),
        "node_count": len(nodes),
        "max_depth": max(node["depth"] for node in nodes) if nodes else 0,
        "nodes": nodes,
    }


def extract_plan_features(
    baseline_plan: Any,
    hypo_plan: Optional[Any] = None,
    hypo_index_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Dual-mode feature extractor:
    - If hypo_plan is provided, runs Decision #10 candidate pair feature extraction.
    - If hypo_plan is None, runs legacy single-plan summary extraction.
    """
    if hypo_plan is not None:
        return extract_candidate_plan_features(
            baseline_plan=baseline_plan,
            hypo_plan=hypo_plan,
            hypo_index_name=hypo_index_name,
        )
    return extract_single_plan_features(baseline_plan)
