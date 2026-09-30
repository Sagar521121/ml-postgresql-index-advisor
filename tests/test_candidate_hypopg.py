from src.index_advisor.candidate_generator import generate_candidates
from src.index_advisor.hypopg_evaluator import evaluate_candidate


BENCHMARK_QUERIES = {
    "Q1_customer_lookup": """
        SELECT *
        FROM orders
        WHERE customer_id = 5000;
    """,

    "Q2_high_amount": """
        SELECT *
        FROM orders
        WHERE amount > 9990;
    """,

    "Q3_cancelled_orders": """
        SELECT *
        FROM orders
        WHERE status = 'cancelled';
    """,

    "Q4_date_lookup": """
        SELECT *
        FROM orders
        WHERE order_date = DATE '2025-06-15';
    """,

    "Q5_customer_city": """
        SELECT *
        FROM customers
        WHERE city = 'Delhi';
    """,

    "Q6_join_city": """
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


def main():

    for query_name, query in BENCHMARK_QUERIES.items():

        print("\n" + "=" * 70)
        print(query_name)
        print("=" * 70)

        candidates = generate_candidates(query)

        if not candidates:
            print("No candidates generated.")
            continue

        for candidate in candidates:

            result = evaluate_candidate(
                query,
                candidate
            )

            candidate_name = (
                f"{candidate['table']}"
                f"({', '.join(candidate['columns'])})"
            )

            print(f"\nCandidate: {candidate_name}")
            print(f"Baseline Cost: {result['baseline_cost']}")
            print(
                f"Hypothetical Cost: "
                f"{result['hypothetical_cost']}"
            )
            print(
                f"Cost Reduction: "
                f"{result['cost_reduction']:.2f}"
            )
            print(
                f"Cost Reduction %: "
                f"{result['cost_reduction_percentage']:.2f}%"
            )
            print(
                f"Hypothetical Root Node: "
                f"{result['root_node_type']}"
            )


if __name__ == "__main__":
    main()
