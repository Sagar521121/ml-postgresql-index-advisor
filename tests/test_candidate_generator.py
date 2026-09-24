from src.index_advisor.candidate_generator import generate_candidates


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

    candidates = generate_candidates(query)

    print("Generated Candidates")
    print("--------------------")

    for candidate in candidates:
        print(candidate)


if __name__ == "__main__":
    main()