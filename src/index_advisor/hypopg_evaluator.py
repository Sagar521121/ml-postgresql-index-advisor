from src.database.connection import get_connection


def evaluate_candidate(query: str, candidate: dict):
    """
    Evaluate a candidate index using HypoPG.
    """

    table = candidate["table"]
    columns = candidate["columns"]

    column_sql = ", ".join(columns)

    index_sql = (
        f"CREATE INDEX ON {table} ({column_sql})"
    )

    with get_connection() as conn:
        with conn.cursor() as cur:

            # Create hypothetical index
            cur.execute(
                """
                SELECT *
                FROM hypopg_create_index(%s);
                """,
                (index_sql,)
            )

            hypothetical_index = cur.fetchone()

            # Ask PostgreSQL for the plan
            cur.execute(
                f"EXPLAIN (FORMAT JSON) {query}"
            )

            plan = cur.fetchone()[0]

            # Reset hypothetical indexes
            cur.execute(
                "SELECT hypopg_reset();"
            )

    root_plan = plan[0]["Plan"]

    return {
        "candidate": candidate,
        "index_sql": index_sql,
        "hypothetical_index": hypothetical_index,
        "root_node_type": root_plan.get("Node Type"),
        "total_cost": root_plan.get("Total Cost"),
        "plan_rows": root_plan.get("Plan Rows"),
        "plan": plan,
    }