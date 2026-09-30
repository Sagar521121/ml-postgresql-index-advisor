from typing import Any, Dict, List, Optional, Tuple
from src.database.connection import get_connection
from src.dataset.session_control import apply_benchmark_session_settings


def _get_plan(cur, query: str):
    apply_benchmark_session_settings(cur)
    cur.execute(f"EXPLAIN (FORMAT JSON) {query}")
    result = cur.fetchone()[0]
    return result[0]["Plan"], result


def _collect_used_indexes(plan_node: dict) -> List[str]:
    """Recursively extract all index names referenced in the plan tree."""
    used_indexes = []

    def walk(node):
        if not isinstance(node, dict):
            return

        index_name = node.get("Index Name")
        if index_name:
            used_indexes.append(index_name)

        for child in node.get("Plans", []):
            walk(child)

    walk(plan_node)
    return used_indexes


def _collect_node_types(plan: dict) -> List[str]:
    """Recursively extract all node types in the plan tree."""
    node_types = []

    def walk(node):
        if not isinstance(node, dict):
            return

        node_type = node.get("Node Type")
        if node_type:
            node_types.append(node_type)

        for child in node.get("Plans", []):
            walk(child)

    walk(plan)
    return node_types


def _get_plan_signature(node: dict) -> Tuple:
    """
    Build a recursive structural signature of the execution plan tree.
    Includes Node Type, Relation Name, Index Name, Join Type, and tree topology.
    """
    if not isinstance(node, dict):
        return ()

    sig = (
        node.get("Node Type"),
        node.get("Relation Name"),
        node.get("Index Name"),
        node.get("Join Type"),
        node.get("Parent Relationship"),
    )

    children_sig = tuple(_get_plan_signature(ch) for ch in node.get("Plans", []))
    return (sig, children_sig)


def _is_plan_structurally_identical(
    baseline_root: dict,
    hypothetical_root: dict,
) -> bool:
    """Check if two plan trees share identical structural topology and operators."""
    return _get_plan_signature(baseline_root) == _get_plan_signature(hypothetical_root)


def _contains_index_related_scan(node_types: List[str]) -> bool:
    """
    Check if generic index scan operators appear anywhere in the node types list.
    Retained as a plan-structure feature; do NOT treat as candidate adoption.
    """
    index_scan_types = {
        "Index Scan",
        "Index Only Scan",
        "Bitmap Index Scan",
        "Bitmap Heap Scan",
    }

    return any(
        node_type in index_scan_types
        for node_type in node_types
    )


def evaluate_candidate(
    query: str,
    candidate: dict,
    dbname: str = "job_imdb",
) -> Dict[str, Any]:
    """
    Evaluate a candidate index using HypoPG against the specified database.

    Safety & Rigor Guarantees:
    - Captures exact hypothetical index name/oid from hypopg_create_index().
    - Recursively checks the entire hypothetical plan for candidate-specific index usage.
    - Classifies plan relationship into:
      * 'candidate_used': candidate index appears in the plan.
      * 'changed_unused': plan changed, but candidate index was not used.
      * 'identical_plan': plan is structurally identical to baseline.
    - Guarantees hypopg_reset() execution in a finally block.
    """
    table = candidate["table"]
    columns = candidate["columns"]

    column_sql = ", ".join(f'"{c}"' for c in columns)
    index_sql = f'CREATE INDEX ON "{table}" ({column_sql})'

    with get_connection(dbname=dbname) as conn:
        with conn.cursor() as cur:
            try:
                # 1. Baseline plan
                baseline_root, baseline_plan = _get_plan(
                    cur,
                    query,
                )

                baseline_cost = float(baseline_root.get("Total Cost", 0.0))
                baseline_node_types = _collect_node_types(baseline_root)
                baseline_used_indexes = _collect_used_indexes(baseline_root)

                # 2. Create hypothetical index
                cur.execute(
                    """
                    SELECT * FROM hypopg_create_index(%s);
                    """,
                    (index_sql,),
                )

                hypothetical_index = cur.fetchone()

                hypo_index_oid: Optional[int] = None
                hypo_index_name: Optional[str] = None
                if hypothetical_index:
                    hypo_index_oid = hypothetical_index[0]
                    hypo_index_name = hypothetical_index[1]

                # 3. Plan with hypothetical index
                hypothetical_root, hypothetical_plan = _get_plan(
                    cur,
                    query,
                )

                hypothetical_cost = float(hypothetical_root.get("Total Cost", 0.0))
                hypothetical_node_types = _collect_node_types(hypothetical_root)
                hypothetical_used_indexes = _collect_used_indexes(hypothetical_root)

                # 4. Candidate-specific index usage verification
                candidate_used = bool(
                    hypo_index_name
                    and (hypo_index_name in hypothetical_used_indexes)
                )

                # 5. Cost comparison
                cost_reduction = baseline_cost - hypothetical_cost
                if baseline_cost > 0:
                    cost_reduction_percentage = (
                        cost_reduction / baseline_cost
                    ) * 100.0
                else:
                    cost_reduction_percentage = 0.0

                # 6. Plan structural comparison & classification
                is_identical = _is_plan_structurally_identical(
                    baseline_root, hypothetical_root
                )
                plan_changed = (not is_identical) or (abs(cost_reduction) > 1e-4)

                if candidate_used:
                    plan_classification = "candidate_used"
                elif plan_changed:
                    plan_classification = "changed_unused"
                else:
                    plan_classification = "identical_plan"

                hypothetical_has_index_scan = _contains_index_related_scan(
                    hypothetical_node_types
                )

                return {
                    "candidate": candidate,
                    "index_sql": index_sql,
                    "hypothetical_index": hypothetical_index,
                    "hypothetical_index_name": hypo_index_name,
                    "hypothetical_index_oid": hypo_index_oid,
                    "candidate_used": candidate_used,
                    "plan_classification": plan_classification,
                    "baseline_cost": baseline_cost,
                    "hypothetical_cost": hypothetical_cost,
                    "total_cost": hypothetical_cost,
                    "cost_reduction": cost_reduction,
                    "cost_reduction_percentage": cost_reduction_percentage,
                    "baseline_node_types": baseline_node_types,
                    "hypothetical_node_types": hypothetical_node_types,
                    "baseline_used_indexes": baseline_used_indexes,
                    "hypothetical_used_indexes": hypothetical_used_indexes,
                    "plan_changed": plan_changed,
                    "hypothetical_has_index_scan": hypothetical_has_index_scan,
                    "root_node_type": hypothetical_root.get("Node Type"),
                    "plan_rows": hypothetical_root.get("Plan Rows"),
                    "baseline_plan": baseline_plan,
                    "plan": hypothetical_plan,
                }
            finally:
                try:
                    cur.execute("SELECT hypopg_reset();")
                except Exception:
                    conn.rollback()
                    try:
                        cur.execute("SELECT hypopg_reset();")
                    except Exception:
                        pass
