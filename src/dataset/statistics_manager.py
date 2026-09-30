from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from src.database.connection import get_connection
from src.dataset.session_control import (
    apply_benchmark_session_settings,
    get_effective_session_settings,
)


def get_statistics_control_snapshot(dbname: str = "job_imdb") -> Dict[str, Any]:
    """
    Capture a reproducible snapshot of PostgreSQL server statistics configuration
    and maintenance settings for the benchmark environment.
    """
    with get_connection(dbname=dbname) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            pg_version = cur.fetchone()[0]

            cur.execute("SELECT current_database();")
            current_db = cur.fetchone()[0]

            cur.execute("SHOW default_statistics_target;")
            default_stats_target = cur.fetchone()[0]

            cur.execute("SHOW autovacuum;")
            autovacuum_global = cur.fetchone()[0]

            # Query server defaults for session parameters before setting session controls
            server_defaults = {}
            try:
                cur.execute("SHOW jit;")
                server_defaults["jit"] = cur.fetchone()[0]
            except Exception:
                pass
            try:
                cur.execute("SHOW max_parallel_workers_per_gather;")
                row = cur.fetchone()
                server_defaults["max_parallel_workers_per_gather"] = int(row[0]) if row and str(row[0]).isdigit() else 0
            except Exception:
                pass
            try:
                cur.execute("SHOW geqo;")
                server_defaults["geqo"] = cur.fetchone()[0]
            except Exception:
                pass

            # Apply and capture benchmark session controls
            apply_benchmark_session_settings(cur)
            effective_session_settings = get_effective_session_settings(cur)

            # Query all user tables in public schema for statistics and storage options
            cur.execute(
                """
                SELECT
                    c.relname,
                    c.reloptions,
                    c.reltuples,
                    c.relpages,
                    (SELECT count(*) FROM pg_stats s WHERE s.schemaname = 'public' AND s.tablename = c.relname) AS stat_columns
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relkind = 'r'
                ORDER BY c.relname;
                """
            )
            rows = cur.fetchall()

    tables_info = {}
    for r in rows:
        tables_info[r[0]] = {
            "reloptions": r[1],
            "reltuples": float(r[2]) if r[2] is not None else 0.0,
            "relpages": int(r[3]) if r[3] is not None else 0,
            "stat_columns": int(r[4]) if r[4] is not None else 0,
        }

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database_name": current_db,
        "postgresql_version": pg_version,
        "default_statistics_target": int(default_stats_target),
        "autovacuum_global": autovacuum_global,
        "table_count": len(tables_info),
        "tables": tables_info,
        "statistics_frozen": True,
        # Decision #8: JIT, GEQO, and Parallelism Control
        "jit": effective_session_settings.get("jit", "off"),
        "max_parallel_workers_per_gather": effective_session_settings.get("max_parallel_workers_per_gather", 0),
        "geqo": effective_session_settings.get("geqo", "off"),
        "session_settings": effective_session_settings,
        "server_defaults": server_defaults,
    }


def run_controlled_vacuum_analyze(
    dbname: str = "job_imdb",
    table_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Perform a single controlled VACUUM ANALYZE preparation step.
    Must be executed with autocommit=True outside any transaction block.
    """
    start_time = datetime.now(timezone.utc).isoformat()
    cmd = f'VACUUM ANALYZE "{table_name}"' if table_name else "VACUUM ANALYZE"

    with get_connection(dbname=dbname) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(cmd)

    end_time = datetime.now(timezone.utc).isoformat()

    return {
        "status": "SUCCESS",
        "command": cmd,
        "database_name": dbname,
        "scope": table_name or "database",
        "started_at": start_time,
        "completed_at": end_time,
    }


def get_table_reloptions(
    dbname: str = "job_imdb",
    tables: Optional[List[str]] = None,
) -> Dict[str, Optional[List[str]]]:
    """Inspect and return current reloptions for public user tables."""
    query = """
        SELECT c.relname, c.reloptions
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r'
    """
    params = []
    if tables:
        query += " AND c.relname = ANY(%s)"
        params.append(tables)
    query += " ORDER BY c.relname;"

    with get_connection(dbname=dbname) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params if params else None)
            rows = cur.fetchall()

    return {r[0]: r[1] for r in rows}


def apply_table_maintenance_policy(
    dbname: str = "job_imdb",
    tables: Optional[List[str]] = None,
    disable_autovacuum: bool = True,
) -> Dict[str, Any]:
    """
    Explicit and reversible per-table maintenance policy:
    - Never modifies server-wide autovacuum setting.
    - Captures original reloptions for each table before modifying.
    - Sets autovacuum_enabled = false per table if requested.
    - Records explicit changes and returns restoration info.
    """
    original_options = get_table_reloptions(dbname=dbname, tables=tables)
    target_tables = sorted(list(original_options.keys()))
    applied_setting = "autovacuum_enabled = false" if disable_autovacuum else "autovacuum_enabled = true"

    with get_connection(dbname=dbname) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            for tbl in target_tables:
                cur.execute(f'ALTER TABLE "{tbl}" SET ({applied_setting});')

    return {
        "status": "APPLIED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database_name": dbname,
        "applied_setting": applied_setting,
        "changed_tables": target_tables,
        "original_options": original_options,
    }


def restore_table_maintenance_policy(
    dbname: str = "job_imdb",
    policy_record: Optional[Dict[str, Any]] = None,
    tables: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Restore original per-table maintenance settings:
    - Reverts autovacuum_enabled per-table settings.
    - Uses RESET (autovacuum_enabled) if table originally had no reloptions.
    - Restores previous reloptions if table had specific settings.
    """
    target_tables = (
        tables
        or (policy_record.get("changed_tables") if policy_record else None)
        or list(get_table_reloptions(dbname=dbname).keys())
    )
    original_options = policy_record.get("original_options", {}) if policy_record else {}

    with get_connection(dbname=dbname) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            for tbl in target_tables:
                orig = original_options.get(tbl)
                if orig:
                    opts_str = ", ".join(orig)
                    cur.execute(f'ALTER TABLE "{tbl}" SET ({opts_str});')
                else:
                    cur.execute(f'ALTER TABLE "{tbl}" RESET (autovacuum_enabled);')

    return {
        "status": "RESTORED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database_name": dbname,
        "restored_tables": target_tables,
    }
