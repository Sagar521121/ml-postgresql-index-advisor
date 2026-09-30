"""
Decision #9 Part 2: Irrelevant-Index Placebo Control.

Implements placebo interventions using an index on a column that is irrelevant
to the tested query's predicates and join conditions.

Locked Protocol:
- Same operational sequence as real candidate indexes:
    CREATE INDEX
        ↓
    warmup (2 warmups)
        ↓
    measured executions (5 measured)
        ↓
    DROP INDEX
- Strictly guaranteed cleanup with catalog verification.
- Clearly marked as control / placebo observation (`is_placebo: True`, `is_control: True`).
- Do NOT use placebo observations as normal training candidates or in candidate rankings.
- Record:
    - query_id
    - placebo index definition
    - creation success
    - baseline runtime
    - placebo runtime
    - raw runtimes
    - planning times
    - execution status
    - cleanup status
    - placebo effect (delta and log-ratio)
    - plan signature, plan hash, plan change event
"""

import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import sqlglot
from sqlglot import exp

from src.dataset.plan_stability import (
    compare_plan_signatures,
    generate_plan_hash,
    generate_plan_signature,
)
from src.dataset.real_benchmark_executor import (
    DEFAULT_REPETITIONS,
    DEFAULT_TIMEOUT_MS,
    DEFAULT_WARMUPS,
)
from src.dataset.real_index_benchmark import (
    EXPERIMENTAL_INDEX_PREFIX,
    benchmark_with_real_index,
    build_create_index_sql,
    make_experimental_index_name,
    verify_index_absent,
)
from src.index_advisor.existing_indexes import get_existing_indexes, is_candidate_covered


# Candidate irrelevant columns across job_imdb tables
CANDIDATE_IRRELEVANT_COLUMNS: List[Tuple[str, str]] = [
    ("company_name", "name_pcode_nf"),
    ("company_name", "surname_pcode"),
    ("company_name", "md5sum"),
    ("aka_name", "name_pcode_nf"),
    ("aka_name", "surname_pcode"),
    ("aka_name", "md5sum"),
    ("aka_title", "phonetic_code"),
    ("aka_title", "md5sum"),
    ("title", "phonetic_code"),
    ("title", "series_years"),
    ("title", "md5sum"),
    ("char_name", "imdb_index"),
    ("char_name", "name_pcode_nf"),
    ("char_name", "surname_pcode"),
    ("char_name", "md5sum"),
    ("comp_cast_type", "kind"),
    ("link_type", "link"),
    ("info_type", "info"),
]


def extract_query_predicates_and_joins_columns(query: str) -> Set[str]:
    """
    Extract all column names that appear in WHERE predicates, JOIN ON conditions,
    or other filtering clauses of the query.
    """
    referenced = set()
    try:
        tree = sqlglot.parse_one(query)
    except Exception:
        # Fallback: simple token scan if sqlglot parse fails
        tokens = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", query)
        return {t.lower() for t in tokens}

    # WHERE conditions
    where = tree.find(exp.Where)
    if where:
        for col in where.find_all(exp.Column):
            referenced.add(col.name.lower())

    # JOIN conditions
    for join in tree.find_all(exp.Join):
        on = join.args.get("on")
        if on:
            for col in on.find_all(exp.Column):
                referenced.add(col.name.lower())

    # HAVING and FILTER clauses
    for having in tree.find_all(exp.Having):
        for col in having.find_all(exp.Column):
            referenced.add(col.name.lower())

    # All table references in query
    for col in tree.find_all(exp.Column):
        referenced.add(col.name.lower())

    return referenced


def select_irrelevant_index_candidate(
    query: str,
    dbname: str = "job_imdb",
    existing_indexes: Optional[Dict[str, Set[Tuple[str, ...]]]] = None,
) -> Dict[str, Any]:
    """
    Select an index candidate on a table and column that is completely
    irrelevant to the query's predicates and join conditions, and not already
    covered by an existing database index.
    """
    query_cols = extract_query_predicates_and_joins_columns(query)

    if existing_indexes is None:
        existing_indexes = get_existing_indexes(dbname=dbname)

    # 1. Search candidate irrelevant columns
    for table, col in CANDIDATE_IRRELEVANT_COLUMNS:
        if col.lower() not in query_cols:
            if not is_candidate_covered(table, (col,), existing_indexes):
                return {
                    "table": table,
                    "columns": [col],
                    "index_type": "btree",
                }

    # Fallback to a safe known placebo
    return {
        "table": "company_name",
        "columns": ["name_pcode_nf"],
        "index_type": "btree",
    }


def run_placebo_benchmark(
    query: str,
    query_id: str,
    placebo_candidate: Optional[Dict[str, Any]] = None,
    repetitions: int = DEFAULT_REPETITIONS,
    warmups: int = DEFAULT_WARMUPS,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    dbname: str = "job_imdb",
    baseline_benchmark: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Run an irrelevant-index placebo intervention following the exact candidate protocol:
        CREATE INDEX -> warmup -> measured executions -> DROP INDEX

    Safety and Control Invariants:
    - Dedicated autocommit cleanup guaranteed.
    - Explicitly marked with is_placebo=True, is_control=True, for_ml_training=False.
    - All 9 required fields recorded and returned.
    """
    if placebo_candidate is None:
        placebo_candidate = select_irrelevant_index_candidate(query, dbname=dbname)

    table = placebo_candidate["table"]
    columns = placebo_candidate["columns"]
    index_type = placebo_candidate.get("index_type", "btree")

    # Generate placebo experimental index name
    cols_str = "_".join(columns)
    raw_name = f"placebo_{table}_{cols_str}"
    index_name = make_experimental_index_name(table, [f"plc_{cols_str}"])
    index_sql = build_create_index_sql(index_name, table, columns)

    # Execute using the exact same operational benchmark pipeline
    benchmark_res = benchmark_with_real_index(
        query=query,
        index_sql=index_sql,
        index_name=index_name,
        table_name=table,
        repetitions=repetitions,
        warmups=warmups,
        timeout_ms=timeout_ms,
        dbname=dbname,
        baseline_benchmark=baseline_benchmark,
        query_id=query_id,
    )

    t_baseline = benchmark_res.get("T_baseline")
    t_placebo = benchmark_res.get("median_runtime_ms")

    # Calculate measured placebo effect
    placebo_signed_log_ratio: Optional[float] = None
    placebo_abs_log_ratio: Optional[float] = None
    placebo_delta_ms: Optional[float] = None

    if t_baseline is not None and t_placebo is not None and benchmark_res["status"] == "SUCCESS":
        # Log ratio: log((T_baseline + 1.0) / (T_placebo + 1.0))
        ratio = (t_baseline + 1.0) / (t_placebo + 1.0)
        placebo_signed_log_ratio = math.log(ratio)
        placebo_abs_log_ratio = abs(placebo_signed_log_ratio)
        placebo_delta_ms = t_placebo - t_baseline

    plan_changed = benchmark_res.get("real_plan_changed", False)
    plan_change_event = bool(plan_changed)

    creation_success = benchmark_res.get("status") != "BENCHMARK_ERROR" or (
        "Failed to create experimental index" not in str(benchmark_res.get("error_message"))
    )

    # Explicitly structured placebo record conforming to Decision #9 Part 2 requirements
    return {
        # Core identification and control marking
        "query_id": query_id,
        "is_placebo": True,
        "is_control": True,
        "control_type": "irrelevant_index_placebo",
        "candidate_type": "placebo",
        "for_ml_training": False,  # MUST NOT be used in ML training or final candidate ranking
        # Required records (Requirement 13)
        "placebo_index_definition": {
            "name": index_name,
            "table": table,
            "columns": columns,
            "index_type": index_type,
            "sql": index_sql,
        },
        "creation_success": creation_success,
        "baseline_runtime": t_baseline,
        "placebo_runtime": t_placebo,
        "raw_runtimes": benchmark_res.get("runtimes_ms", []),
        "planning_times": benchmark_res.get("planning_times_ms", []),
        "execution_status": benchmark_res.get("status"),
        "cleanup_status": benchmark_res.get("cleanup_verified", False),
        # Measured placebo effect (Requirement 14: not assumed to be zero)
        "placebo_effect_signed_log_ratio": placebo_signed_log_ratio,
        "placebo_effect_abs_log_ratio": placebo_abs_log_ratio,
        "placebo_delta_ms": placebo_delta_ms,
        # Plan stability monitoring (Requirement 19, 20)
        "baseline_plan_signature": benchmark_res.get("baseline_plan_signature"),
        "baseline_plan_hash": benchmark_res.get("baseline_plan_hash"),
        "placebo_plan_signature": benchmark_res.get("real_plan_signature"),
        "placebo_plan_hash": benchmark_res.get("real_plan_hash"),
        "plan_changed": plan_changed,
        "plan_change_event": plan_change_event,
        # Underlying benchmark details
        "benchmark_details": benchmark_res,
        "metadata": metadata or {},
    }
