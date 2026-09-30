"""
Decision #12: Full Benchmark Execution / Data Collection Protocol
Enhanced with robust Checkpoint + Resume, Atomic Persistence,
Graceful Interruption, and Leftover Index Protection.
"""
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple, Union
import sqlglot
from sqlglot import exp

from src.database.connection import get_connection
from src.dataset.baseline_manager import BaselineManager
from src.dataset.checkpoint_manager import CheckpointManager
from src.dataset.dataset_builder import DatasetBuilder
from src.dataset.real_index_benchmark import (
    EXPERIMENTAL_INDEX_PREFIX,
    benchmark_with_real_index,
    build_create_index_sql,
    cleanup_leftover_experimental_indexes,
    verify_index_absent,
)
from src.dataset.statistics_manager import get_statistics_control_snapshot
from src.features.plan_features import extract_candidate_plan_features
from src.index_advisor.candidate_generator import generate_candidates
from src.index_advisor.hypopg_evaluator import evaluate_candidate

logger = logging.getLogger(__name__)


def generate_candidate_id(table: str, columns: List[str]) -> str:
    return f"cand_{table}_{'_'.join(columns)}"


def get_experimental_index_name(table: str, columns: List[str]) -> str:
    # Ensuring it follows the exp_idx_ prefix policy
    return f"{EXPERIMENTAL_INDEX_PREFIX}{table}_{'_'.join(columns)}"


def generate_placebo_candidate(query: str) -> Optional[Dict]:
    """
    Generate an irrelevant-index placebo candidate.
    Uses a standard JOB table/column that is effectively irrelevant for
    most meaningful performance interventions.
    """
    tree = sqlglot.parse_one(query)
    # Extract all tables to pick one actually present in the query
    tables = [t.name.lower() for t in tree.find_all(exp.Table)]

    # Common JOB tables and a column that is almost never filtered on.
    # Note: These columns must physically exist in the IMDB schema.
    # 'md5sum' exists on title, name, char_name, etc.
    # 'note' exists on movie_info, person_info, etc.
    for table_name in tables:
        if table_name == 'title': return {"table": "title", "columns": ["md5sum"], "index_type": "btree"}
        if table_name == 'name': return {"table": "name", "columns": ["md5sum"], "index_type": "btree"}
        if table_name == 'char_name': return {"table": "char_name", "columns": ["md5sum"], "index_type": "btree"}
        if table_name == 'person_info': return {"table": "person_info", "columns": ["note"], "index_type": "btree"}
        if table_name == 'movie_info': return {"table": "movie_info", "columns": ["note"], "index_type": "btree"}
        if table_name == 'movie_companies': return {"table": "movie_companies", "columns": ["note"], "index_type": "btree"}

    # Fallback to an arbitrary one if parsed poorly, though it may fail if not in query.
    return {"table": "title", "columns": ["md5sum"], "index_type": "btree"}


def reset_hypopg_state(dbname: str = "job_imdb") -> None:
    """Ensure HypoPG hypothetical indexes are clean."""
    try:
        with get_connection(dbname=dbname) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT hypopg_reset();")
    except Exception as e:
        logger.warning(f"HypoPG reset encountered non-fatal error: {e}")


def run_benchmark_collection(
    queries: Dict[str, str],
    dbname: str = "job_imdb",
    pilot: bool = False,
    pilot_max_pairs: int = 20,
    checkpoint_path: Optional[str] = "experiments/benchmark_checkpoint.jsonl",
) -> DatasetBuilder:
    """
    Execute the full benchmark data collection protocol with Checkpoint + Resume.

    Features:
    - Per-candidate atomic checkpointing
    - Automatic detection and skip of already-completed pairs
    - Safe recovery from crashes / power loss / Ctrl+C
    - Pre-candidate and startup sweeps of leftover experimental indexes
    - Guaranteed cleanup and database state verification
    """
    builder = DatasetBuilder()
    baseline_manager = BaselineManager(dbname=dbname)

    # If using default benchmark checkpoint path but in pilot mode, switch to pilot checkpoint
    if checkpoint_path == "experiments/benchmark_checkpoint.jsonl" and pilot:
        checkpoint_path = "experiments/pilot_checkpoint.jsonl"

    checkpoint_mgr: Optional[CheckpointManager] = None
    completed_keys: Set[Tuple[str, str]] = set()

    if checkpoint_path:
        checkpoint_mgr = CheckpointManager(checkpoint_path=checkpoint_path)
        restored = checkpoint_mgr.populate_builder(builder)
        completed_keys = checkpoint_mgr.get_completed_keys()
        logger.info(
            f"CheckpointManager loaded {restored} observations ({len(completed_keys)} unique keys) "
            f"from {checkpoint_path}"
        )

    # 1. Startup cleanup sweep for experimental indexes and HypoPG state
    dropped = cleanup_leftover_experimental_indexes(dbname=dbname)
    if dropped:
        logger.warning(f"Startup sweep dropped {len(dropped)} leftover experimental indexes: {dropped}")
        for idx in dropped:
            if not verify_index_absent(idx, dbname=dbname):
                raise RuntimeError(f"Startup cleanup failed: index {idx} still present!")
    reset_hypopg_state(dbname=dbname)

    # Gather all evaluations (candidates, A/A, Placebo)
    all_pairs = []
    for q_id, q_text in queries.items():
        try:
            cands = generate_candidates(q_text)
            for c in cands:
                all_pairs.append({
                    "type": "candidate",
                    "q_id": q_id,
                    "q_text": q_text,
                    "cand": c,
                })

            # Decision #9: Schedule Controls
            # A/A Control
            all_pairs.append({
                "type": "aa_control",
                "q_id": q_id,
                "q_text": q_text,
                "cand": None,
            })

            # Placebo Control
            placebo = generate_placebo_candidate(q_text)
            if placebo:
                all_pairs.append({
                    "type": "placebo",
                    "q_id": q_id,
                    "q_text": q_text,
                    "cand": placebo,
                })
        except Exception as e:
            logger.warning(f"Failed to generate candidates for {q_id}: {e}")

    if pilot:
        logger.info(f"PILOT MODE: Filtering down to ~{pilot_max_pairs} pairs.")
        target_queries = ["1a", "3a", "14a", "24a", "11a", "2a"]

        pilot_pairs = []
        q_dict = {}
        for item in all_pairs:
            q_dict.setdefault(item["q_id"], []).append(item)

        for target in target_queries:
            if target in q_dict:
                for item in q_dict[target]:
                    pilot_pairs.append(item)
                    if len(pilot_pairs) >= pilot_max_pairs:
                        break
            if len(pilot_pairs) >= pilot_max_pairs:
                break

        if len(pilot_pairs) < pilot_max_pairs:
            for q_id, items in q_dict.items():
                if q_id not in target_queries:
                    for item in items:
                        pilot_pairs.append(item)
                        if len(pilot_pairs) >= pilot_max_pairs:
                            break
                if len(pilot_pairs) >= pilot_max_pairs:
                    break

        all_pairs = pilot_pairs

    logger.info(f"Total iterations to benchmark: {len(all_pairs)} (already completed: {len(completed_keys)})")

    try:
        for i, item in enumerate(all_pairs, 1):
            q_id = item["q_id"]
            q_text = item["q_text"]
            cand = item["cand"]
            run_type = item["type"]
            family_id = q_id.replace("a", "").replace("b", "").replace("c", "").replace("d", "")

            # Determine unique candidate_id
            if run_type == "aa_control":
                cand_id = "aa_control"
                cand_def = {"table": "none", "columns": [], "sql": "none"}
            elif run_type == "placebo":
                cand_id = "placebo_" + generate_candidate_id(cand["table"], cand["columns"])
                cand_def = cand.copy()
            else:
                cand_id = generate_candidate_id(cand["table"], cand["columns"])
                cand_def = cand.copy()

            # Checkpoint check: skip already-completed pairs
            pair_key = (q_id, cand_id)
            if pair_key in completed_keys:
                logger.info(f"--- [{i}/{len(all_pairs)}] Query: {q_id}, ID: {cand_id} -> ALREADY COMPLETED. Skipping. ---")
                continue

            logger.info(f"--- [{i}/{len(all_pairs)}] Query: {q_id}, Type: {run_type}, ID: {cand_id} ---")

            # Pre-candidate safety sweep: clean any leftover experimental indexes
            leftover = cleanup_leftover_experimental_indexes(dbname=dbname)
            if leftover:
                logger.warning(f"Pre-candidate safety sweep dropped leftover experimental indexes: {leftover}")
                for idx in leftover:
                    if not verify_index_absent(idx, dbname=dbname):
                        raise RuntimeError(f"Database dirty: failed to clean up leftover index {idx}")
            reset_hypopg_state(dbname=dbname)

            # 1. Measure fresh baseline block immediately prior to candidate creation.
            # This solves the cache asymmetry bias (Baseline -> Candidate symmetry).
            baseline_result = baseline_manager.request_fresh_baseline(
                query=q_text,
                query_id=q_id,
                reason=f"pairing_for_{run_type}",
                # Enforce exactly 2 warmups, 5 measured
                warmups=2,
                repetitions=5,
            )
            if baseline_result["status"] != "SUCCESS":
                logger.warning(f"Baseline failed for {q_id}. Skipping {run_type}.")
                # Record failure in checkpoint to avoid infinite retry loops on corrupt query
                if checkpoint_mgr:
                    checkpoint_mgr.save_record({
                        "query_id": q_id,
                        "candidate_id": cand_id,
                        "run_type": run_type,
                        "family_id": family_id,
                        "structural_unit_id": family_id,
                        "status": "BENCHMARK_ERROR",
                        "timed_out": False,
                        "cleanup_verified": True,
                        "error_message": f"Baseline failed: {baseline_result.get('error_message')}",
                        "candidate_def": cand_def,
                        "features": {},
                        "metadata": {},
                        "target": None,
                        "target_type": None,
                        "label_is_censored": False,
                        "rejection_reason": "baseline_failure",
                        "raw_measurements": {},
                        "plan_info": {},
                        "outcome": baseline_result,
                    })
                continue

            baseline_plan = baseline_result["plan"]
            stats_snap = get_statistics_control_snapshot(dbname=dbname)

            if run_type == "aa_control":
                # A/A Control Execution
                aa_result = baseline_manager.request_fresh_baseline(
                    query=q_text,
                    query_id=q_id,
                    reason="aa_control_measurement",
                    warmups=2,
                    repetitions=5,
                )

                outcome = dict(aa_result)
                outcome["is_aa_control"] = True
                outcome["actual_runtime_ms"] = aa_result.get("median_runtime_ms")
                # Link it clearly to the baseline measured just above
                outcome["baseline_block_id"] = baseline_result["baseline_block_id"]
                outcome["T_baseline"] = baseline_result.get("median_runtime_ms")
                outcome["cleanup_verified"] = True

                builder.add_observation(
                    query_id=q_id,
                    family_id=family_id,
                    candidate_id=cand_id,
                    candidate_def=cand_def,
                    baseline_plan=baseline_plan,
                    hypo_plan=baseline_plan,
                    benchmark_outcome=outcome,
                )

                if checkpoint_mgr:
                    checkpoint_mgr.save_record({
                        "query_id": q_id,
                        "candidate_id": cand_id,
                        "run_type": run_type,
                        "family_id": family_id,
                        "structural_unit_id": family_id,
                        "status": aa_result.get("status", "SUCCESS"),
                        "timed_out": aa_result.get("timed_out", False),
                        "cleanup_verified": True,
                        "error_message": aa_result.get("error_message"),
                        "candidate_def": cand_def,
                        "features": {},
                        "metadata": {},
                        "target": None,
                        "target_type": None,
                        "label_is_censored": False,
                        "rejection_reason": "aa_control",
                        "raw_measurements": {
                            "candidate_runtimes_ms": aa_result.get("runtimes_ms", []),
                            "candidate_planning_times_ms": aa_result.get("planning_times_ms", []),
                            "candidate_median_runtime_ms": aa_result.get("median_runtime_ms"),
                            "candidate_median_planning_time_ms": aa_result.get("median_planning_time_ms"),
                            "baseline_runtimes_ms": baseline_result.get("runtimes_ms", []),
                            "baseline_planning_times_ms": baseline_result.get("planning_times_ms", []),
                            "baseline_median_runtime_ms": baseline_result.get("median_runtime_ms"),
                            "timeout_limit_ms": None,
                        },
                        "plan_info": {
                            "baseline_plan_hash": baseline_result.get("baseline_plan_hash") or baseline_result.get("plan_hash"),
                        },
                        "outcome": outcome,
                    })
                completed_keys.add(pair_key)
                continue

            idx_name = get_experimental_index_name(cand["table"], cand["columns"])
            idx_sql = build_create_index_sql(idx_name, cand["table"], cand["columns"])
            cand_def["sql"] = idx_sql

            # 2. Obtain HypoPG candidate plan
            try:
                hypo_result = evaluate_candidate(q_text, cand, dbname=dbname)
                hypo_plan = hypo_result["plan"]
                hypo_index_name = hypo_result.get("hypothetical_index_name")
            except Exception as e:
                logger.warning(f"HypoPG evaluation failed for {q_id}/{cand_id}: {e}")
                if checkpoint_mgr:
                    checkpoint_mgr.save_record({
                        "query_id": q_id,
                        "candidate_id": cand_id,
                        "run_type": run_type,
                        "family_id": family_id,
                        "structural_unit_id": family_id,
                        "status": "BENCHMARK_ERROR",
                        "timed_out": False,
                        "cleanup_verified": True,
                        "error_message": f"HypoPG error: {e}",
                        "candidate_def": cand_def,
                        "features": {},
                        "metadata": {},
                        "target": None,
                        "target_type": None,
                        "label_is_censored": False,
                        "rejection_reason": "hypopg_failure",
                        "raw_measurements": {},
                        "plan_info": {},
                        "outcome": {"status": "BENCHMARK_ERROR", "error_message": str(e)},
                    })
                completed_keys.add(pair_key)
                continue

            # 3. Create, Benchmark, and Drop real index
            real_result = benchmark_with_real_index(
                query=q_text,
                index_sql=idx_sql,
                index_name=idx_name,
                table_name=cand["table"],
                query_id=q_id,
                baseline_benchmark=baseline_result, # Feed the exactly paired baseline
                baseline_manager=baseline_manager,
                statistics_snapshot=stats_snap,
                dbname=dbname,
                warmups=2,
                repetitions=5,
            )

            if not real_result["cleanup_verified"]:
                logger.error(f"CRITICAL: Cleanup failed for {idx_name}! Stopping benchmark safely.")
                cleanup_leftover_experimental_indexes(dbname=dbname)
                raise RuntimeError(f"Cleanup failed during full benchmark. System left dirty: {idx_name}")

            if run_type == "placebo":
                real_result["is_placebo"] = True

            # 4. Add observation (extracts features and computes targets)
            added_row = builder.add_observation(
                query_id=q_id,
                family_id=family_id,
                candidate_id=cand_id,
                candidate_def=cand_def,
                baseline_plan=baseline_plan,
                hypo_plan=hypo_plan,
                hypo_index_name=hypo_index_name,
                benchmark_outcome=real_result,
            )

            # Determine rejection reason and feature/metadata dictionaries
            rejection_reason: Optional[str] = None
            if run_type == "placebo":
                rejection_reason = "placebo_control"
            elif real_result.get("status") == "BENCHMARK_ERROR":
                rejection_reason = "benchmark_error"
            elif added_row is None:
                # Look up rejection reason from builder
                if builder.rejected and builder.rejected[-1]["candidate_id"] == cand_id:
                    rejection_reason = builder.rejected[-1]["reason"]

            if added_row is not None:
                features_dict = dict(added_row.features)
                metadata_dict = dict(added_row.metadata)
                target_val = metadata_dict.get("target")
                target_type_val = metadata_dict.get("target_type")
                censored_val = bool(metadata_dict.get("label_is_censored"))
            else:
                try:
                    features_dict = extract_candidate_plan_features(
                        baseline_plan=baseline_plan,
                        hypo_plan=hypo_plan,
                        hypo_index_name=hypo_index_name,
                    )
                except Exception:
                    features_dict = {}
                metadata_dict = {
                    "query_id": q_id,
                    "family_id": family_id,
                    "candidate_id": cand_id,
                    "status": real_result.get("status"),
                }
                target_val = real_result.get("target")
                target_type_val = real_result.get("target_type")
                censored_val = bool(real_result.get("label_is_censored", False))

            # 5. Atomic Checkpoint persistence
            if checkpoint_mgr:
                checkpoint_record = {
                    "query_id": q_id,
                    "candidate_id": cand_id,
                    "run_type": run_type,
                    "family_id": family_id,
                    "structural_unit_id": family_id,
                    "status": real_result.get("status"),
                    "timed_out": real_result.get("timed_out", False),
                    "cleanup_verified": real_result.get("cleanup_verified", False),
                    "error_message": real_result.get("error_message"),
                    "candidate_def": cand_def,
                    "features": features_dict,
                    "metadata": metadata_dict,
                    "target": target_val,
                    "target_type": target_type_val,
                    "label_is_censored": censored_val,
                    "rejection_reason": rejection_reason,
                    "raw_measurements": {
                        "candidate_runtimes_ms": real_result.get("runtimes_ms", []),
                        "candidate_planning_times_ms": real_result.get("planning_times_ms", []),
                        "candidate_median_runtime_ms": real_result.get("median_runtime_ms"),
                        "candidate_median_planning_time_ms": real_result.get("median_planning_time_ms"),
                        "baseline_runtimes_ms": real_result.get("baseline_runtimes_ms", []),
                        "baseline_planning_times_ms": real_result.get("baseline_planning_times_ms", []),
                        "baseline_median_runtime_ms": real_result.get("baseline_median_runtime_ms"),
                        "timeout_limit_ms": real_result.get("timeout_limit_ms"),
                    },
                    "plan_info": {
                        "candidate_used_in_hypo_plan": features_dict.get("candidate_used_in_hypo_plan") if features_dict else None,
                        "real_candidate_used": real_result.get("real_candidate_used"),
                        "real_plan_changed": real_result.get("real_plan_changed"),
                        "real_plan_hash": real_result.get("real_plan_hash"),
                        "baseline_plan_hash": real_result.get("baseline_plan_hash"),
                    },
                    "outcome": real_result,
                }
                checkpoint_mgr.save_record(checkpoint_record)

            completed_keys.add(pair_key)

    except KeyboardInterrupt:
        logger.warning("\n[INTERRUPTED] Benchmark received KeyboardInterrupt (SIGINT). Stopping safely...")
        print("\n[INTERRUPTED] Benchmark received KeyboardInterrupt. Cleaning up database...")
        dropped_on_interrupt = cleanup_leftover_experimental_indexes(dbname=dbname)
        reset_hypopg_state(dbname=dbname)
        if dropped_on_interrupt:
            print(f"[INTERRUPTED] Cleaned up in-flight experimental indexes: {dropped_on_interrupt}")
        completed_count = len(checkpoint_mgr.get_completed_keys()) if checkpoint_mgr else len(builder.rows)
        print(f"[INTERRUPTED] Benchmark stopped safely. {completed_count} observations checkpointed.")
        print(f"[INTERRUPTED] To resume, rerun the benchmark command with the same checkpoint path.")
        raise

    return builder
