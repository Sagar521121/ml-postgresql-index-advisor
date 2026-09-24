from src.index_advisor.candidate_generator import generate_candidates
from src.index_advisor.hypopg_evaluator import evaluate_candidate


def main():

    query = """
    SELECT
        c.customer_id,
        c.city,
        o.amount
    FROM customers c
    JOIN orders o
        ON c.customer_id = o.customer_id
    WHERE c.city = 'Delhi';
    """

    # Step 1: Generate candidates
    candidates = generate_candidates(query)

    print("Generated Candidates")
    print("--------------------")

    for candidate in candidates:
        print(candidate)

    # Step 2: Evaluate every candidate with HypoPG
    print("\nHypoPG Evaluation")
    print("-----------------")

    for candidate in candidates:

        result = evaluate_candidate(
            query,
            candidate
        )

        print(
            f"{candidate['table']}({', '.join(candidate['columns'])})"
            f" → "
            f"{result['root_node_type']}"
            f" | cost={result['total_cost']}"
            f" | rows={result['plan_rows']}"
        )


if __name__ == "__main__":
    main()