from src.index_advisor.hypopg_evaluator import evaluate_candidate


def main():

    query = """
    SELECT *
    FROM orders
    WHERE customer_id = 5000;
    """

    candidate = {
        "table": "orders",
        "columns": ["customer_id"],
        "index_type": "btree",
    }

    result = evaluate_candidate(query, candidate)

    print("HypoPG Evaluation")
    print("-----------------")
    print(f"Candidate: {result['candidate']}")
    print(f"Index SQL: {result['index_sql']}")
    print(f"Root Node: {result['root_node_type']}")
    print(f"Total Cost: {result['total_cost']}")
    print(f"Estimated Rows: {result['plan_rows']}")


if __name__ == "__main__":
    main()