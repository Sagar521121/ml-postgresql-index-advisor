from typing import Dict, List, Set, Tuple, Union
from src.database.connection import get_connection


def get_existing_indexes(
    dbname: str = "job_imdb",
) -> Dict[str, Set[Tuple[str, ...]]]:
    """
    Return existing valid indexes in the public schema for the specified database,
    grouped by table name as a set of column tuples.

    Uses PostgreSQL system catalogs (pg_index, pg_class, pg_attribute, pg_am, pg_namespace)
    to accurately detect single-column, composite, and primary-key indexes.

    Result format:
    {
        "movie_companies": {
            ("id",),
            ("company_id",),
            ("company_type_id",),
            ("movie_id",),
        },
        ...
    }
    """
    query = """
        SELECT
            t.relname AS table_name,
            i.relname AS index_name,
            ix.indisprimary AS is_primary,
            am.amname AS index_type,
            array_agg(a.attname ORDER BY array_position(ix.indkey, a.attnum)) AS columns
        FROM pg_index ix
        JOIN pg_class t ON t.oid = ix.indrelid
        JOIN pg_class i ON i.oid = ix.indexrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        JOIN pg_am am ON am.oid = i.relam
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
        WHERE n.nspname = 'public'
          AND ix.indisvalid
          AND t.relkind = 'r'
        GROUP BY t.relname, i.relname, ix.indisprimary, am.amname
        ORDER BY t.relname, i.relname;
    """

    indexes: Dict[str, Set[Tuple[str, ...]]] = {}
    target_db = dbname or "job_imdb"

    with get_connection(dbname=target_db) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()

    for table_name, _index_name, _is_primary, _index_type, columns in rows:
        col_tuple = tuple(col.lower() for col in columns)
        indexes.setdefault(table_name.lower(), set()).add(col_tuple)

    return indexes


def get_existing_index_details(dbname: str = "job_imdb") -> List[Dict]:
    """
    Return detailed metadata for existing indexes in the specified database.
    Useful for diagnostic reporting, index verification, and audits.
    """
    query = """
        SELECT
            t.relname AS table_name,
            i.relname AS index_name,
            ix.indisprimary AS is_primary,
            am.amname AS index_type,
            array_agg(a.attname ORDER BY array_position(ix.indkey, a.attnum)) AS columns
        FROM pg_index ix
        JOIN pg_class t ON t.oid = ix.indrelid
        JOIN pg_class i ON i.oid = ix.indexrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        JOIN pg_am am ON am.oid = i.relam
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
        WHERE n.nspname = 'public'
          AND ix.indisvalid
          AND t.relkind = 'r'
        GROUP BY t.relname, i.relname, ix.indisprimary, am.amname
        ORDER BY t.relname, i.relname;
    """

    target_db = dbname or "job_imdb"
    details = []

    with get_connection(dbname=target_db) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()

    for table_name, index_name, is_primary, index_type, columns in rows:
        details.append({
            "table_name": table_name.lower(),
            "index_name": index_name,
            "is_primary": bool(is_primary),
            "index_type": index_type,
            "columns": tuple(col.lower() for col in columns),
        })

    return details


def is_candidate_covered(
    table: str,
    candidate_columns: Union[List[str], Tuple[str, ...]],
    existing_indexes: Dict[str, Set[Tuple[str, ...]]],
) -> bool:
    """
    Check if a candidate index on a table is covered or made redundant
    by any existing index on that table.

    Rules:
    - Exact match: If an existing index matches candidate_columns exactly, candidate is redundant.
    - Composite leading prefix: If candidate is (c_1, ..., c_k) and an existing index is
      (e_1, ..., e_m) where m >= k and (e_1, ..., e_k) == (c_1, ..., c_k), the candidate is redundant
      because the existing B-tree index already indexes that prefix.
    - Single-column vs composite: A single-column candidate on 'c_1' is covered by an existing
      composite index on ('c_1', 'c_2'). However, a composite candidate on ('c_1', 'c_2') is NOT
      covered by a single-column index on ('c_1',).
    """
    candidate_cols = tuple(c.lower() for c in candidate_columns)
    k = len(candidate_cols)
    if k == 0:
        return False

    table_indexes = existing_indexes.get(table.lower(), set())

    for existing_cols in table_indexes:
        if len(existing_cols) >= k and existing_cols[:k] == candidate_cols:
            return True

    return False
