from pathlib import Path
from src.index_advisor.candidate_generator import generate_candidates


def test_synthetic_query_candidates():
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

    # In ml_index_advisor, customers.customer_id is a PK index
    candidates_ml = generate_candidates(query, dbname="ml_index_advisor")
    tables_cols_ml = [(c["table"], tuple(c["columns"])) for c in candidates_ml]

    assert ("customers", ("customer_id",)) not in tables_cols_ml, (
        "customers(customer_id) should be filtered out by ml_index_advisor existing PK"
    )
    assert ("customers", ("city",)) in tables_cols_ml
    assert ("orders", ("customer_id",)) in tables_cols_ml
    print("Synthetic query candidate filtering on ml_index_advisor PASSED!")


def test_job_query_candidates():
    job_1a_path = Path("benchmarks/job/1a.sql")
    if not job_1a_path.exists():
        print(f"Skipping JOB 1a test: {job_1a_path} not found")
        return

    query_1a = job_1a_path.read_text(encoding="utf-8")
    candidates = generate_candidates(query_1a, dbname="job_imdb")
    tables_cols = [(c["table"], tuple(c["columns"])) for c in candidates]

    # Rejection of existing PKs
    assert ("title", ("id",)) not in tables_cols, "title(id) is a PK and must be filtered out"
    assert ("company_type", ("id",)) not in tables_cols, "company_type(id) is a PK and must be filtered out"
    assert ("info_type", ("id",)) not in tables_cols, "info_type(id) is a PK and must be filtered out"

    # Rejection of existing FK indexes
    assert ("movie_companies", ("movie_id",)) not in tables_cols, (
        "movie_companies(movie_id) is an existing FK index and must be filtered out"
    )
    assert ("movie_companies", ("company_type_id",)) not in tables_cols, (
        "movie_companies(company_type_id) is an existing FK index and must be filtered out"
    )
    assert ("movie_info_idx", ("movie_id",)) not in tables_cols, (
        "movie_info_idx(movie_id) is an existing FK index and must be filtered out"
    )
    assert ("movie_info_idx", ("info_type_id",)) not in tables_cols, (
        "movie_info_idx(info_type_id) is an existing FK index and must be filtered out"
    )

    # Retention of legitimate new candidates
    assert ("company_type", ("kind",)) in tables_cols, "company_type(kind) should be kept"
    assert ("info_type", ("info",)) in tables_cols, "info_type(info) should be kept"
    assert ("movie_companies", ("note",)) in tables_cols, "movie_companies(note) should be kept"

    print(f"JOB 1a.sql candidate generation on job_imdb PASSED! ({len(candidates)} candidates kept)")


def main():
    print("Testing synthetic candidate generator...")
    test_synthetic_query_candidates()

    print("\nTesting JOB 1a candidate generator on job_imdb...")
    test_job_query_candidates()


if __name__ == "__main__":
    main()
