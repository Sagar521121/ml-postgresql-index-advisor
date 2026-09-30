"""
Checkpoint + Resume Manager for PostgreSQL ML Benchmark.

Provides per-candidate checkpointing with atomic disk persistence,
safe resumption, duplicate protection, and full preservation of raw
runtime arrays, plan signatures, and metadata.
"""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from src.dataset.dataset_builder import DatasetBuilder, DatasetRow

logger = logging.getLogger(__name__)


class CheckpointManager:
    """
    Manages per-candidate checkpoint persistence and recovery.

    Guarantees:
    - Atomic writes: writes to a temporary file, fsyncs, and atomically renames.
    - Zero data loss: every completed candidate/control is checkpointed immediately.
    - Safe resume: completed (query_id, candidate_id) pairs are loaded and skipped.
    - Duplicate prevention: each (query_id, candidate_id) appears at most once.
    - Raw data preservation: preserves all raw runtimes, planning times, plans,
      signatures, and metadata.
    """

    def __init__(self, checkpoint_path: Union[str, Path] = "experiments/benchmark_checkpoint.jsonl"):
        self.checkpoint_path = Path(checkpoint_path).resolve()
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self._records: List[Dict[str, Any]] = []
        self._completed_keys: Set[Tuple[str, str]] = set()
        self._load_existing()

    @property
    def path(self) -> Path:
        return self.checkpoint_path

    def _load_existing(self) -> None:
        """
        Load existing checkpoint file if it exists.
        Supports JSONL (line-by-line) or JSON array format.
        Tolerates trailing partial lines from sudden power loss or process kill.
        """
        if not self.checkpoint_path.exists():
            return

        if self.checkpoint_path.stat().st_size == 0:
            return

        try:
            content = self.checkpoint_path.read_text(encoding="utf-8").strip()
        except Exception as e:
            logger.error(f"Failed to read checkpoint file {self.checkpoint_path}: {e}")
            return

        if not content:
            return

        # Format detection: JSON array/object vs JSON Lines
        if content.startswith("[") or (content.startswith("{") and "\n" not in content):
            try:
                data = json.loads(content)
                if isinstance(data, list):
                    records = data
                elif isinstance(data, dict):
                    records = data.get("records")
                    if records is None:
                        records = [data]
                else:
                    records = []
                for rec in records:
                    if isinstance(rec, dict):
                        self._ingest_record(rec)
                logger.info(f"Loaded {len(self._records)} records from JSON checkpoint: {self.checkpoint_path}")
                return
            except json.JSONDecodeError:
                pass  # Fall back to line-by-line reading

        # Parse line-by-line (JSON Lines)
        lines = content.splitlines()
        loaded = 0
        corrupted = 0
        for line_no, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if self._ingest_record(rec):
                    loaded += 1
            except json.JSONDecodeError as err:
                corrupted += 1
                logger.warning(
                    f"Ignored corrupted line {line_no} in checkpoint {self.checkpoint_path}: {err}"
                )

        logger.info(
            f"Loaded {loaded} valid checkpoint records from {self.checkpoint_path} "
            f"({corrupted} malformed/partial lines ignored)."
        )

    def _ingest_record(self, rec: Dict[str, Any]) -> bool:
        """Internal helper to ingest a record with deduplication."""
        q_id = rec.get("query_id")
        c_id = rec.get("candidate_id")
        if not q_id or not c_id:
            return False

        key = (str(q_id), str(c_id))
        if key in self._completed_keys:
            return False

        self._records.append(rec)
        self._completed_keys.add(key)
        return True

    def is_completed(self, query_id: str, candidate_id: str) -> bool:
        """Check whether a (query_id, candidate_id) observation was already completed."""
        return (str(query_id), str(candidate_id)) in self._completed_keys

    def get_completed_keys(self) -> Set[Tuple[str, str]]:
        """Return a copy of the completed (query_id, candidate_id) keys set."""
        return set(self._completed_keys)

    def get_records(self) -> List[Dict[str, Any]]:
        """Return a copy of all loaded records."""
        return list(self._records)

    def count(self) -> int:
        """Return count of completed records."""
        return len(self._records)

    def save_record(self, record: Dict[str, Any]) -> bool:
        """
        Atomically persist a single completed observation record.

        Steps:
        1. Deduplicate in-memory.
        2. Write to a temporary file in the same directory.
        3. Flush and fsync the file descriptor to physical disk.
        4. Atomically replace the target checkpoint file.

        Returns True if newly saved, False if already existed.
        """
        q_id = record.get("query_id")
        c_id = record.get("candidate_id")
        if not q_id or not c_id:
            raise ValueError(f"Checkpoint record missing query_id or candidate_id: {record}")

        key = (str(q_id), str(c_id))
        if key in self._completed_keys:
            logger.debug(f"Record {key} already exists in checkpoint; skipping duplicate write.")
            return False

        if "timestamp" not in record:
            record["timestamp"] = datetime.now(timezone.utc).isoformat()

        self._records.append(record)
        self._completed_keys.add(key)

        # Atomic persistence via temporary file + fsync + atomic rename
        temp_path = self.checkpoint_path.with_name(f"{self.checkpoint_path.name}.tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                for r in self._records:
                    f.write(json.dumps(r) + "\n")
                f.flush()
                os.fsync(f.fileno())

            os.replace(temp_path, self.checkpoint_path)
            return True
        except Exception as e:
            logger.error(f"Failed to atomically persist checkpoint to {self.checkpoint_path}: {e}")
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            raise

    def populate_builder(self, builder: DatasetBuilder) -> int:
        """
        Populate a DatasetBuilder instance with all completed records from the checkpoint.
        Ensures both accepted ML rows and rejected control/error rows are restored.

        Returns count of restored records.
        """
        restored = 0
        for rec in self._records:
            q_id = rec.get("query_id")
            c_id = rec.get("candidate_id")
            pair_key = (q_id, c_id)

            if pair_key in builder._seen_pairs:
                continue

            rejection_reason = rec.get("rejection_reason")
            features = rec.get("features")
            metadata = rec.get("metadata")

            if rejection_reason is None and features and metadata:
                # Accepted ML candidate row
                row = DatasetRow(features=features, metadata=metadata)
                builder._rows.append(row)
                builder._seen_pairs.add(pair_key)
                restored += 1
            else:
                # Rejected control, timeout-reject, or benchmark-error row
                builder._rejected.append({
                    "query_id": q_id,
                    "candidate_id": c_id,
                    "reason": rejection_reason or "unknown_rejection",
                    "status": rec.get("status"),
                    "outcome": rec.get("outcome", {}),
                })
                builder._seen_pairs.add(pair_key)
                restored += 1

        return restored

    def summary(self) -> Dict[str, Any]:
        """Return summary statistics of checkpointed records."""
        statuses = [r.get("status") for r in self._records]
        types = [r.get("run_type") for r in self._records]
        rejections = [r.get("rejection_reason") for r in self._records if r.get("rejection_reason")]

        return {
            "total_records": len(self._records),
            "checkpoint_path": str(self.checkpoint_path),
            "status_counts": {s: statuses.count(s) for s in set(statuses) if s},
            "type_counts": {t: types.count(t) for t in set(types) if t},
            "rejections_count": len(rejections),
        }
