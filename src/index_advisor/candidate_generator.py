from typing import Dict, List, Optional, Set, Tuple
from src.index_advisor.existing_indexes import (
    get_existing_indexes,
    is_candidate_covered,
)
import sqlglot
from sqlglot import exp


def generate_candidates(
    query: str,
    dbname: str = "job_imdb",
    existing_indexes: Optional[Dict[str, Set[Tuple[str, ...]]]] = None,
) -> List[Dict]:
    """
    Generate single-column B-tree index candidates
    from WHERE and JOIN conditions.
    """

    tree = sqlglot.parse_one(query)

    candidates = []

    # -------------------------------------------------
    # Build alias -> real table mapping
    # -------------------------------------------------

    table_map = {}

    for table in tree.find_all(exp.Table):
        table_name = table.name
        alias = table.alias_or_name
        table_map[alias] = table_name

    # -------------------------------------------------
    # Helper function
    # -------------------------------------------------

    def add_candidate(column):
        column_name = column.name
        table_reference = column.table

        if table_reference:
            table_name = table_map.get(
                table_reference,
                table_reference
            )
        else:
            if len(table_map) == 1:
                table_name = next(iter(table_map.values()))
            else:
                table_name = None

        if table_name:
            candidates.append({
                "table": table_name,
                "columns": [column_name],
                "index_type": "btree",
            })

    # -------------------------------------------------
    # WHERE candidates
    # -------------------------------------------------

    where = tree.find(exp.Where)

    if where:
        for column in where.find_all(exp.Column):
            add_candidate(column)

    # -------------------------------------------------
    # JOIN candidates
    # -------------------------------------------------

    for join in tree.find_all(exp.Join):

        on_condition = join.args.get("on")

        if on_condition:
            for column in on_condition.find_all(exp.Column):
                add_candidate(column)

       # Remove duplicates
    unique_candidates = []

    for candidate in candidates:
        if candidate not in unique_candidates:
            unique_candidates.append(candidate)

    # Remove candidates that already exist as indexes or are covered by existing indexes
    if existing_indexes is None:
        existing_indexes = get_existing_indexes(dbname=dbname)

    filtered_candidates = []

    for candidate in unique_candidates:

        table = candidate["table"]
        columns = tuple(candidate["columns"])

        if is_candidate_covered(table, columns, existing_indexes):
            continue

        filtered_candidates.append(candidate)

    return filtered_candidates
