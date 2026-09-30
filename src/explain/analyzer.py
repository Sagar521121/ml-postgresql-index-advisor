from src.database.connection import get_connection
from src.dataset.session_control import apply_benchmark_session_settings


def explain_query(query: str):
    explain_query = f"EXPLAIN (FORMAT JSON) {query}"

    with get_connection() as conn:
        with conn.cursor() as cur:
            apply_benchmark_session_settings(cur)
            cur.execute(explain_query)
            result = cur.fetchone()

    return result[0]
