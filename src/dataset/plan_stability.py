"""
Decision #9 Part 3: Plan Stability Monitoring.

Provides deterministic structural plan signature extraction, hashing,
and stability comparison for PostgreSQL JSON execution plans.

The structural signature strictly excludes:
- execution timing (Execution Time, Planning Time, Actual Startup/Total Time)
- actual rows and loops (Actual Rows, Actual Loops, Rows Removed)
- runtime buffer / I/O stats (Shared/Local/Temp Hit/Read/Written Blocks)
- query execution IDs and timestamps
- cost estimates and plan widths that might fluctuate with statistics

The structural signature captures:
- node types
- parent/child structure and hierarchy
- relation names and aliases
- index names
- scan direction and join types
- filter / join / index condition expressions
- group and sort keys
"""

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple, Union


STRUCTURAL_KEYS = (
    "Node Type",
    "Parent Relationship",
    "Relation Name",
    "Alias",
    "Index Name",
    "Scan Direction",
    "Join Type",
    "Strategy",
    "Partial Mode",
    "Inner Unique",
    "Hash Cond",
    "Index Cond",
    "Recheck Cond",
    "Merge Cond",
    "Filter",
    "Join Filter",
)

LIST_STRUCTURAL_KEYS = (
    "Group Key",
    "Sort Key",
)


def _unwrap_plan_root(plan: Any) -> Optional[Dict[str, Any]]:
    """Unwrap top-level EXPLAIN JSON structure to obtain the root Plan dict."""
    if plan is None:
        return None
    if isinstance(plan, list):
        if len(plan) == 0:
            return None
        plan = plan[0]
    if isinstance(plan, dict):
        if "Plan" in plan and isinstance(plan["Plan"], dict):
            return plan["Plan"]
        return plan
    return None


def extract_structural_plan(plan_or_node: Any) -> Optional[Dict[str, Any]]:
    """
    Extract a clean dictionary containing ONLY the structural properties of
    the plan tree, explicitly omitting all runtime statistics, timings,
    actual row counts, buffer stats, and costs.
    """
    root = _unwrap_plan_root(plan_or_node)
    if not isinstance(root, dict):
        return None

    def walk(node: Dict[str, Any]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key in STRUCTURAL_KEYS:
            val = node.get(key)
            if val is not None:
                result[key] = val

        for key in LIST_STRUCTURAL_KEYS:
            val = node.get(key)
            if val is not None:
                if isinstance(val, (list, tuple)):
                    result[key] = [str(x) for x in val]
                else:
                    result[key] = [str(val)]

        children = node.get("Plans", [])
        if isinstance(children, list) and children:
            result["Plans"] = [walk(ch) for ch in children if isinstance(ch, dict)]
        else:
            result["Plans"] = []

        return result

    return walk(root)


def generate_plan_signature(plan_or_node: Any) -> Tuple:
    """
    Generate a deterministic recursive tuple signature representing the
    structural plan hierarchy.
    """
    root = _unwrap_plan_root(plan_or_node)
    if not isinstance(root, dict):
        return ()

    def walk(node: Dict[str, Any]) -> Tuple:
        node_props = []
        for key in STRUCTURAL_KEYS:
            node_props.append((key, node.get(key)))

        for key in LIST_STRUCTURAL_KEYS:
            val = node.get(key)
            if val is not None:
                if isinstance(val, (list, tuple)):
                    node_props.append((key, tuple(str(x) for x in val)))
                else:
                    node_props.append((key, (str(val),)))
            else:
                node_props.append((key, None))

        children = node.get("Plans", [])
        children_sig = tuple(
            walk(ch) for ch in children if isinstance(ch, dict)
        )
        return (tuple(node_props), children_sig)

    return walk(root)


def generate_plan_hash(plan_or_node: Any) -> Optional[str]:
    """
    Generate a deterministic SHA-256 hex digest of the canonical structural plan.
    Returns None if plan_or_node is None or empty.
    """
    structural = extract_structural_plan(plan_or_node)
    if structural is None:
        return None

    canonical_json = json.dumps(structural, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def compare_plan_signatures(
    plan_a: Any,
    plan_b: Any,
) -> Dict[str, Any]:
    """
    Compare the structural signatures and hashes of two execution plans.

    Returns:
    - is_identical: True if structural signatures match exactly.
    - plan_changed: True if structural signature changed.
    - plan_change_event: True if structural signature changed (diagnostic event).
    - signature_a: structural signature tuple of plan A.
    - signature_b: structural signature tuple of plan B.
    - hash_a: deterministic SHA-256 hash of plan A.
    - hash_b: deterministic SHA-256 hash of plan B.
    """
    sig_a = generate_plan_signature(plan_a)
    sig_b = generate_plan_signature(plan_b)

    hash_a = generate_plan_hash(plan_a)
    hash_b = generate_plan_hash(plan_b)

    if hash_a is None or hash_b is None:
        # One or both plans could not be hashed
        is_identical = (sig_a == sig_b and hash_a == hash_b and hash_a is not None)
        plan_changed = not is_identical
    else:
        is_identical = (hash_a == hash_b and sig_a == sig_b)
        plan_changed = not is_identical

    return {
        "is_identical": is_identical,
        "plan_changed": plan_changed,
        "plan_change_event": plan_changed,
        "signature_a": sig_a,
        "signature_b": sig_b,
        "hash_a": hash_a,
        "hash_b": hash_b,
    }
