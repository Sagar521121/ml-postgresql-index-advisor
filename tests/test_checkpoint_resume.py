"""
Unit & Integration Tests for Checkpoint + Resume Mechanism (Decision #12).

Tests:
- Checkpoint write and atomic persistence
- Checkpoint reload and corruption resilience
- Resume skipping already-completed candidates
- Duplicate candidate prevention
- TIMEOUT persistence and censoring preservation
- BENCHMARK_ERROR persistence and quarantine
- Interrupted candidate handling (Ctrl+C / KeyboardInterrupt)
- Pre-candidate leftover experimental index cleanup
- Raw runtime array preservation
- Database cleanliness invariant verification
"""

import json
from pathlib import Path
import pytest
from unittest.mock import MagicMock, call, patch

from src.database.connection import get_connection
from src.dataset.checkpoint_manager import CheckpointManager
from src.dataset.dataset_builder import DatasetBuilder
from src.dataset.real_index_benchmark import (
    EXPERIMENTAL_INDEX_PREFIX,
    cleanup_leftover_experimental_indexes,
    verify_index_absent,
)
from src.dataset.runner import run_benchmark_collection
from src.features.plan_features import FEATURE_SCHEMA
from src.index_advisor.existing_indexes import get_existing_index_details


def test_checkpoint_manager_atomic_write_and_reload(tmp_path: Path):
    """Verify that records are written atomically and reloaded identically."""
    chk_file = tmp_path / "test_checkpoint.jsonl"
    mgr = CheckpointManager(checkpoint_path=chk_file)

    rec1 = {
        "query_id": "1a",
        "candidate_id": "cand_title_production_year",
        "run_type": "candidate",
        "status": "SUCCESS",
        "features": {f"f{i}": float(i) for i in range(74)},
        "metadata": {"query_id": "1a", "candidate_id": "cand_title_production_year", "status": "SUCCESS"},
        "raw_measurements": {"candidate_runtimes_ms": [10.1, 10.2, 10.3, 10.4, 10.5]},
    }
    rec2 = {
        "query_id": "1a",
        "candidate_id": "aa_control",
        "run_type": "aa_control",
        "status": "SUCCESS",
        "rejection_reason": "aa_control",
        "raw_measurements": {"candidate_runtimes_ms": [20.1, 20.2, 20.3, 20.4, 20.5]},
    }

    assert mgr.save_record(rec1) is True
    assert mgr.save_record(rec2) is True
    assert mgr.count() == 2
    assert mgr.is_completed("1a", "cand_title_production_year") is True
    assert mgr.is_completed("1a", "aa_control") is True
    assert mgr.is_completed("1a", "nonexistent") is False

    # Check that temporary file does not linger
    assert not (tmp_path / "test_checkpoint.jsonl.tmp").exists()
    assert chk_file.exists()

    # Reload in a completely fresh CheckpointManager instance
    mgr2 = CheckpointManager(checkpoint_path=chk_file)
    assert mgr2.count() == 2
    assert mgr2.is_completed("1a", "cand_title_production_year") is True
    assert mgr2.is_completed("1a", "aa_control") is True

    # Test tolerance for partial trailing lines (e.g. from power outage)
    with open(chk_file, "a", encoding="utf-8") as f:
        f.write('{"query_id": "2a", "candidate_id": "partial_cand", "sta\n')

    mgr3 = CheckpointManager(checkpoint_path=chk_file)
    # The valid 2 records are preserved; the partial line is skipped without crash
    assert mgr3.count() == 2
    assert mgr3.is_completed("1a", "cand_title_production_year") is True


def test_checkpoint_manager_duplicate_prevention(tmp_path: Path):
    """Verify that attempting to save duplicate candidate records is rejected."""
    chk_file = tmp_path / "test_dupes.jsonl"
    mgr = CheckpointManager(checkpoint_path=chk_file)

    rec = {
        "query_id": "3a",
        "candidate_id": "cand_test_col",
        "run_type": "candidate",
        "status": "SUCCESS",
    }
    assert mgr.save_record(rec) is True
    # Attempting to save identical (query_id, candidate_id)
    assert mgr.save_record(rec) is False
    assert mgr.count() == 1


def test_checkpoint_manager_timeout_persistence(tmp_path: Path):
    """Verify that TIMEOUT records are saved, reloaded, and preserve censorship metadata."""
    chk_file = tmp_path / "test_timeout.jsonl"
    mgr = CheckpointManager(checkpoint_path=chk_file)

    timeout_rec = {
        "query_id": "14a",
        "candidate_id": "cand_movie_info_note",
        "run_type": "candidate",
        "status": "TIMEOUT",
        "timed_out": True,
        "label_is_censored": True,
        "target": -0.405,
        "target_type": "bound_derived",
        "rejection_reason": None,
        "features": {k: 0.0 for k in FEATURE_SCHEMA},
        "metadata": {
            "query_id": "14a",
            "candidate_id": "cand_movie_info_note",
            "status": "TIMEOUT",
            "actual_indexed_runtime_ms": None,
            "label_is_censored": True,
            "target": -0.405,
            "target_type": "bound_derived",
        },
        "raw_measurements": {"timeout_limit_ms": 30000.0},
    }

    mgr.save_record(timeout_rec)

    # Populate a DatasetBuilder
    builder = DatasetBuilder()
    restored = mgr.populate_builder(builder)
    assert restored == 1
    assert len(builder.rows) == 1
    row = builder.rows[0]
    assert row.metadata["status"] == "TIMEOUT"
    assert row.metadata["actual_indexed_runtime_ms"] is None
    assert row.metadata["label_is_censored"] is True
    assert row.metadata["target"] == -0.405


def test_checkpoint_manager_benchmark_error_persistence(tmp_path: Path):
    """Verify that BENCHMARK_ERROR records remain quarantined and are not falsely converted to SUCCESS."""
    chk_file = tmp_path / "test_error.jsonl"
    mgr = CheckpointManager(checkpoint_path=chk_file)

    error_rec = {
        "query_id": "24a",
        "candidate_id": "cand_syntax_error",
        "run_type": "candidate",
        "status": "BENCHMARK_ERROR",
        "rejection_reason": "benchmark_error",
        "error_message": "DDL Timeout: Failed to create experimental index within 60000ms.",
        "outcome": {"status": "BENCHMARK_ERROR", "error_message": "DDL Timeout"},
    }

    mgr.save_record(error_rec)

    builder = DatasetBuilder()
    restored = mgr.populate_builder(builder)
    assert restored == 1
    assert len(builder.rows) == 0  # Excluded from ML training rows!
    assert len(builder.rejected) == 1
    assert builder.rejected[0]["status"] == "BENCHMARK_ERROR"
    assert builder.rejected[0]["reason"] == "benchmark_error"


def test_checkpoint_manager_raw_data_preservation(tmp_path: Path):
    """Verify that raw runtime arrays and plan metadata survive checkpointing intact."""
    chk_file = tmp_path / "test_raw.jsonl"
    mgr = CheckpointManager(checkpoint_path=chk_file)

    rec = {
        "query_id": "11a",
        "candidate_id": "cand_rich_metadata",
        "run_type": "candidate",
        "status": "SUCCESS",
        "raw_measurements": {
            "candidate_runtimes_ms": [10.5, 11.2, 10.8, 10.9, 11.0],
            "candidate_planning_times_ms": [1.1, 1.2, 1.0, 1.1, 1.3],
            "candidate_median_runtime_ms": 10.9,
            "candidate_median_planning_time_ms": 1.1,
            "baseline_runtimes_ms": [25.0, 26.1, 24.8, 25.2, 25.4],
            "baseline_planning_times_ms": [1.5, 1.4, 1.6, 1.5, 1.5],
            "baseline_median_runtime_ms": 25.2,
            "timeout_limit_ms": 37800.0,
        },
        "plan_info": {
            "real_candidate_used": True,
            "real_plan_changed": True,
            "real_plan_hash": "a1b2c3d4",
            "baseline_plan_hash": "e5f6g7h8",
        },
    }

    mgr.save_record(rec)

    mgr2 = CheckpointManager(checkpoint_path=chk_file)
    loaded = mgr2.get_records()[0]
    assert loaded["raw_measurements"]["candidate_runtimes_ms"] == [10.5, 11.2, 10.8, 10.9, 11.0]
    assert loaded["raw_measurements"]["baseline_runtimes_ms"] == [25.0, 26.1, 24.8, 25.2, 25.4]
    assert loaded["plan_info"]["real_candidate_used"] is True
    assert loaded["plan_info"]["real_plan_hash"] == "a1b2c3d4"


def test_resume_simulation_with_keyboard_interrupt(tmp_path: Path):
    """
    TASK 3 Test: Deterministic simulation of benchmark interruption and restart.

    Sequence:
    Candidate 1 -> SUCCESS
    Candidate 2 -> SUCCESS
    Candidate 3 -> SUCCESS
    Candidate 4 -> KeyboardInterrupt (Ctrl+C)
    [Process dies, leaving database in safe state]
    Restart:
    Candidate 1 -> SKIPPED
    Candidate 2 -> SKIPPED
    Candidate 3 -> SKIPPED
    Candidate 4 -> executed normally -> SUCCESS
    Candidate 5 -> executed normally -> SUCCESS

    Verifies:
    - Candidates 1-3 are not rerun on restart
    - Candidate 4 is not falsely marked complete before completion
    - No duplicate rows exist
    - All 5 results are present after restart
    - Zero experimental indexes remain in database
    """
    chk_file = tmp_path / "resume_test.jsonl"

    queries = {
        "1a": "SELECT 1 FROM title WHERE production_year = 2000;",
        "2a": "SELECT 1 FROM company_name WHERE name = 'Universal';",
        "3a": "SELECT 1 FROM keyword WHERE keyword = 'action';",
        "4a": "SELECT 1 FROM movie_info WHERE info = 'USA';",
        "5a": "SELECT 1 FROM cast_info WHERE role_id = 1;",
    }

    execution_calls = []

    def mock_benchmark_real(query, index_name, **kwargs):
        execution_calls.append(index_name)
        # Simulate interruption during Candidate 4
        if "movie_info" in query:
            raise KeyboardInterrupt("Simulated Ctrl+C during candidate 4!")
        return {
            "status": "SUCCESS",
            "cleanup_verified": True,
            "T_baseline": 100.0,
            "actual_runtime_ms": 50.0,
            "timeout_limit_ms": 30000.0,
            "runtimes_ms": [50.0] * 5,
            "planning_times_ms": [1.0] * 5,
            "median_runtime_ms": 50.0,
            "median_planning_time_ms": 1.0,
        }

    valid_plan = {"Plan": {"Node Type": "Seq Scan"}}

    # RUN 1: Interruption on Candidate 4
    with patch("src.dataset.runner.benchmark_with_real_index", side_effect=mock_benchmark_real), \
         patch("src.dataset.runner.evaluate_candidate") as mock_eval, \
         patch("src.dataset.runner.BaselineManager") as mock_bm_cls, \
         patch("src.dataset.runner.generate_candidates") as mock_gen, \
         patch("src.dataset.runner.generate_placebo_candidate", return_value=None):

        mock_gen.side_effect = lambda q: [{"table": "t", "columns": ["c"], "index_type": "btree"}]
        mock_eval.return_value = {"plan": valid_plan, "hypothetical_index_name": "hypo"}
        mock_bm = mock_bm_cls.return_value
        mock_bm.request_fresh_baseline.return_value = {
            "status": "SUCCESS",
            "plan": valid_plan,
            "baseline_block_id": "b1",
            "median_runtime_ms": 100.0,
            "runtimes_ms": [100.0] * 5,
            "planning_times_ms": [1.0] * 5,
        }

        # Run 1 is expected to raise KeyboardInterrupt when it hits Candidate 4
        with pytest.raises(KeyboardInterrupt):
            run_benchmark_collection(
                queries=queries,
                pilot=False,
                checkpoint_path=str(chk_file),
            )

    # Verify state after Run 1:
    mgr_after_run1 = CheckpointManager(checkpoint_path=chk_file)
    completed_keys_run1 = mgr_after_run1.get_completed_keys()

    # 1a, 2a, 3a completed (each had candidate + aa_control)
    assert ("1a", "cand_t_c") in completed_keys_run1
    assert ("2a", "cand_t_c") in completed_keys_run1
    assert ("3a", "cand_t_c") in completed_keys_run1
    # 4a and 5a must NOT be complete!
    assert ("4a", "cand_t_c") not in completed_keys_run1
    assert ("5a", "cand_t_c") not in completed_keys_run1

    # RUN 2: Resume / Restart (Candidate 4 now succeeds without interruption)
    execution_calls_run2 = []

    def mock_benchmark_real_run2(query, index_name, **kwargs):
        execution_calls_run2.append(index_name)
        return {
            "status": "SUCCESS",
            "cleanup_verified": True,
            "T_baseline": 100.0,
            "actual_runtime_ms": 45.0,
            "timeout_limit_ms": 30000.0,
            "runtimes_ms": [45.0] * 5,
            "planning_times_ms": [1.0] * 5,
            "median_runtime_ms": 45.0,
            "median_planning_time_ms": 1.0,
        }

    with patch("src.dataset.runner.benchmark_with_real_index", side_effect=mock_benchmark_real_run2), \
         patch("src.dataset.runner.evaluate_candidate") as mock_eval, \
         patch("src.dataset.runner.BaselineManager") as mock_bm_cls, \
         patch("src.dataset.runner.generate_candidates") as mock_gen, \
         patch("src.dataset.runner.generate_placebo_candidate", return_value=None):

        mock_gen.side_effect = lambda q: [{"table": "t", "columns": ["c"], "index_type": "btree"}]
        mock_eval.return_value = {"plan": valid_plan, "hypothetical_index_name": "hypo"}
        mock_bm = mock_bm_cls.return_value
        mock_bm.request_fresh_baseline.return_value = {
            "status": "SUCCESS",
            "plan": valid_plan,
            "baseline_block_id": "b1",
            "median_runtime_ms": 100.0,
            "runtimes_ms": [100.0] * 5,
            "planning_times_ms": [1.0] * 5,
        }

        # Run 2: Resume using the SAME checkpoint file
        builder_resumed = run_benchmark_collection(
            queries=queries,
            pilot=False,
            checkpoint_path=str(chk_file),
        )

    # Verification of Resume Behavior:
    # 1. Candidates 1, 2, 3 were NOT rerun in Run 2!
    for idx_call in execution_calls_run2:
        # None of the 1a, 2a, 3a candidate calls should have happened in Run 2
        assert "1a" not in idx_call and "2a" not in idx_call and "3a" not in idx_call

    # 2. Only candidates 4a and 5a were executed in Run 2
    assert len(execution_calls_run2) == 2

    # 3. Checkpoint now contains all 5 queries
    mgr_after_run2 = CheckpointManager(checkpoint_path=chk_file)
    completed_keys_run2 = mgr_after_run2.get_completed_keys()
    assert ("1a", "cand_t_c") in completed_keys_run2
    assert ("2a", "cand_t_c") in completed_keys_run2
    assert ("3a", "cand_t_c") in completed_keys_run2
    assert ("4a", "cand_t_c") in completed_keys_run2
    assert ("5a", "cand_t_c") in completed_keys_run2

    # 4. Builder contains all observations without duplicates
    query_ids_in_builder = [r.metadata["query_id"] for r in builder_resumed.rows]
    assert len(query_ids_in_builder) == 5
    assert set(query_ids_in_builder) == {"1a", "2a", "3a", "4a", "5a"}


def test_pre_candidate_cleanup_sweep_on_leftover_index():
    """Verify that a leftover experimental index from a prior crash is safely swept before starting a candidate."""
    test_index = f"{EXPERIMENTAL_INDEX_PREFIX}test_leftover_cleanup_sweep"

    # Intentionally plant a leftover experimental index
    with get_connection("job_imdb") as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'DROP INDEX IF EXISTS "{test_index}"')
            cur.execute(f'CREATE INDEX "{test_index}" ON company_type (kind)')

    assert not verify_index_absent(test_index, "job_imdb")

    # Run startup / pre-candidate sweep
    dropped = cleanup_leftover_experimental_indexes("job_imdb")
    assert test_index in dropped
    assert verify_index_absent(test_index, "job_imdb")


def test_database_cleanliness_invariants():
    """
    TASK 4 Test: Verify all database cleanliness invariants.
    1. Permanent index count == 44
    2. Experimental indexes count == 0
    3. HypoPG state == 0
    """
    details = get_existing_index_details("job_imdb")
    assert len(details) == 44, f"Expected 44 permanent indexes, found {len(details)}"

    exp_indexes = [d for d in details if d["index_name"].startswith(EXPERIMENTAL_INDEX_PREFIX)]
    assert len(exp_indexes) == 0, f"Found unexpected experimental indexes: {exp_indexes}"

    with get_connection("job_imdb") as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM hypopg();")
            hypo_rows = cur.fetchall()
            assert len(hypo_rows) == 0, f"Found leftover HypoPG indexes: {hypo_rows}"
