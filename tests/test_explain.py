from src.explain.analyzer import explain_query
from src.features.plan_features import extract_plan_features


QUERIES = {
    "Sequential Scan": """
        SELECT *
        FROM orders
        WHERE amount > 9000;
    """,

    "Bitmap Scan": """
        SELECT *
        FROM orders
        WHERE customer_id = 5000;
    """,

    "Hash Join": """
        SELECT
            c.customer_id,
            c.city,
            o.amount
        FROM customers c
        JOIN orders o
            ON c.customer_id = o.customer_id
        WHERE c.city = 'Delhi';
    """
}


def print_plan_tree(nodes):
    for node in nodes:
        indentation = "  " * node["depth"]

        print(
            f"{indentation}"
            f"{node['node_type']} | "
            f"relation={node['relation']} | "
            f"cost={node['total_cost']} | "
            f"rows={node['plan_rows']}"
        )


def main():

    for name, query in QUERIES.items():

        print("\n" + "=" * 60)
        print(name)
        print("=" * 60)

        plan = explain_query(query)

        features = extract_plan_features(plan)

        print(f"Root Node: {features['root_node_type']}")
        print(f"Root Relation: {features['root_relation']}")
        print(f"Total Cost: {features['root_total_cost']}")
        print(f"Estimated Rows: {features['root_plan_rows']}")
        print(f"Node Count: {features['node_count']}")
        print(f"Maximum Depth: {features['max_depth']}")

        print("\nPlan Tree")
        print("---------")

        print_plan_tree(features["nodes"])


if __name__ == "__main__":
    main()