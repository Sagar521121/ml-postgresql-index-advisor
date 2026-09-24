def walk_plan(node, depth=0):
    """
    Recursively walk through a PostgreSQL execution plan tree.
    """

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
        features.extend(walk_plan(child, depth + 1))

    return features


def extract_plan_features(plan):
    """
    Extract features from the complete PostgreSQL execution plan.
    """

    root = plan[0]["Plan"]

    nodes = walk_plan(root)

    return {
        "root_node_type": root.get("Node Type"),
        "root_relation": root.get("Relation Name"),
        "root_startup_cost": root.get("Startup Cost"),
        "root_total_cost": root.get("Total Cost"),
        "root_plan_rows": root.get("Plan Rows"),
        "root_plan_width": root.get("Plan Width"),

        "node_count": len(nodes),
        "max_depth": max(node["depth"] for node in nodes),

        "nodes": nodes,
    }