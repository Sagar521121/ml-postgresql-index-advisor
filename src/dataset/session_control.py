"""
Session-level configuration and control for PostgreSQL execution environment.
Implements Decision #8: PostgreSQL JIT, GEQO, and Parallelism Control.

LOCKED SESSION SETTINGS:
    jit = off
    max_parallel_workers_per_gather = 0
    geqo = off

RATIONALE:
These settings are experimental controls intended to reduce execution/planner
variability and make the benchmark environment reproducible.
The benchmark is making a controlled-environment claim, not a claim about
default PostgreSQL behavior.
"""

from typing import Any, Dict, List, Optional

LOCKED_SESSION_SETTINGS: Dict[str, Any] = {
    "jit": "off",
    "max_parallel_workers_per_gather": 0,
    "geqo": "off",
}


def apply_benchmark_session_settings(cursor) -> Dict[str, Any]:
    """
    Apply locked benchmark session settings directly to the active cursor/connection.
    Applies ONLY at the session level without altering server-wide configuration:
        SET jit = off;
        SET max_parallel_workers_per_gather = 0;
        SET geqo = off;
    Returns the effective settings for the session.
    """
    cursor.execute("SET jit = off;")
    cursor.execute("SET max_parallel_workers_per_gather = 0;")
    cursor.execute("SET geqo = off;")
    return get_effective_session_settings(cursor)


def get_effective_session_settings(cursor) -> Dict[str, Any]:
    """
    Query and return current session effective settings for jit,
    max_parallel_workers_per_gather, and geqo.
    Includes defensive parsing for mock/test cursors.
    """
    jit_val = "off"
    parallel_val = 0
    geqo_val = "off"

    try:
        cursor.execute("SHOW jit;")
        row = cursor.fetchone()
        if row and isinstance(row, (tuple, list)) and len(row) > 0:
            val_str = str(row[0]).strip().lower()
            if val_str in ("on", "off"):
                jit_val = val_str
    except Exception:
        pass

    try:
        cursor.execute("SHOW max_parallel_workers_per_gather;")
        row = cursor.fetchone()
        if row and isinstance(row, (tuple, list)) and len(row) > 0:
            val_str = str(row[0]).strip()
            if val_str.isdigit():
                parallel_val = int(val_str)
    except Exception:
        pass

    try:
        cursor.execute("SHOW geqo;")
        row = cursor.fetchone()
        if row and isinstance(row, (tuple, list)) and len(row) > 0:
            val_str = str(row[0]).strip().lower()
            if val_str in ("on", "off"):
                geqo_val = val_str
    except Exception:
        pass

    return {
        "jit": jit_val,
        "max_parallel_workers_per_gather": parallel_val,
        "geqo": geqo_val,
    }


def verify_plan_parallel_and_jit(plan_json: Any) -> Dict[str, bool]:
    """
    Inspect an EXPLAIN / EXPLAIN ANALYZE result dictionary or tree to determine:
    - has_parallel_nodes: True if any Gather, Gather Merge, or parallel workers exist
    - has_jit: True if top-level 'JIT' block exists
    """
    has_jit = False
    has_parallel_nodes = False

    top_dict = plan_json
    if isinstance(plan_json, list) and len(plan_json) > 0:
        top_dict = plan_json[0]

    if isinstance(top_dict, dict):
        if "JIT" in top_dict and top_dict["JIT"] is not None:
            has_jit = True

        root_node = top_dict.get("Plan", top_dict)

        def walk(node):
            nonlocal has_parallel_nodes
            if not isinstance(node, dict):
                return
            node_type = str(node.get("Node Type", ""))
            if "Gather" in node_type or "Parallel" in node_type:
                has_parallel_nodes = True
            if node.get("Workers Planned", 0) > 0:
                has_parallel_nodes = True
            for child in node.get("Plans", []):
                walk(child)

        walk(root_node)

    return {
        "has_parallel_nodes": has_parallel_nodes,
        "has_jit": has_jit,
    }
