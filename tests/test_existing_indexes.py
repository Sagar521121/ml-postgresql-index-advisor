from src.index_advisor.existing_indexes import (
    get_existing_indexes,
    get_existing_index_details,
    is_candidate_covered,
)


def test_existing_indexes_job_imdb():
    """Verify index detection on job_imdb."""
    indexes = get_existing_indexes(dbname="job_imdb")
    details = get_existing_index_details(dbname="job_imdb")

    total_indexes = sum(len(cols) for cols in indexes.values())
    print(f"Total index entries detected in job_imdb: {total_indexes}")
    print(f"Total detailed index records: {len(details)}")
    print(f"Total indexed tables: {len(indexes)}")

    assert len(details) == 44, f"Expected 44 indexes in job_imdb, found {len(details)}"

    # Check representative indexes
    assert ("id",) in indexes.get("title", set()), "Expected title(id) PK"
    assert ("id",) in indexes.get("movie_companies", set()), "Expected movie_companies(id) PK"
    assert ("movie_id",) in indexes.get("movie_companies", set()), "Expected movie_companies(movie_id) FK index"
    assert ("info_type_id",) in indexes.get("movie_info_idx", set()), "Expected movie_info_idx(info_type_id) FK index"

    # Verify coverage checks
    # 1. movie_companies(movie_id) is already indexed -> must be covered (True)
    assert is_candidate_covered("movie_companies", ["movie_id"], indexes) is True, (
        "movie_companies(movie_id) should be recognized as covered"
    )

    # 2. movie_info_idx(info_type_id, movie_id) exact composite does not exist -> must NOT be covered (False)
    assert is_candidate_covered("movie_info_idx", ["info_type_id", "movie_id"], indexes) is False, (
        "movie_info_idx(info_type_id, movie_id) should NOT be recognized as covered"
    )

    # 3. movie_info_idx(info_type_id) single-column exists -> must be covered (True)
    assert is_candidate_covered("movie_info_idx", ["info_type_id"], indexes) is True, (
        "movie_info_idx(info_type_id) should be recognized as covered"
    )

    # 4. Primary key title(id) -> must be covered (True)
    assert is_candidate_covered("title", ["id"], indexes) is True, (
        "title(id) should be recognized as covered"
    )

    print("All job_imdb index assertions PASSED!")


def test_covering_rules_unit():
    """Unit tests for composite leading-prefix and single-column covering rules."""
    synthetic_indexes = {
        "orders": {
            ("customer_id", "order_date"),  # composite index
            ("status",),                     # single-column index
        }
    }

    # Leading column of composite index is covered
    assert is_candidate_covered("orders", ["customer_id"], synthetic_indexes) is True
    # Exact composite index is covered
    assert is_candidate_covered("orders", ["customer_id", "order_date"], synthetic_indexes) is True
    # Non-leading column of composite index is NOT covered
    assert is_candidate_covered("orders", ["order_date"], synthetic_indexes) is False
    # Wider composite than existing is NOT covered
    assert is_candidate_covered("orders", ["customer_id", "order_date", "amount"], synthetic_indexes) is False
    # Exact single column is covered
    assert is_candidate_covered("orders", ["status"], synthetic_indexes) is True
    # Composite starting with single column is NOT covered by single-column index
    assert is_candidate_covered("orders", ["status", "amount"], synthetic_indexes) is False

    print("All unit coverage assertions PASSED!")


def main():
    print("Testing existing index detection on job_imdb...")
    test_existing_indexes_job_imdb()

    print("\nTesting synthetic coverage rules...")
    test_covering_rules_unit()

    print("\nSample detected indexes from job_imdb:")
    details = get_existing_index_details("job_imdb")
    for d in details[:8]:
        pk_str = " (PK)" if d["is_primary"] else ""
        print(f"  {d['table_name']}.{d['index_name']}{pk_str} -> {list(d['columns'])}")


if __name__ == "__main__":
    main()
