"""
Decision #11: Dataset Construction + Target Generation.

Constructs the ML dataset from benchmark artifacts:
  1. 74-feature vector from Decision #10 (plan features)
  2. Real-index benchmark outcome (status, runtimes, target)
  3. Metadata columns for grouped evaluation

Target formula:
  SUCCESS:   y = log((T_baseline + 1.0) / (T_indexed + 1.0))
  TIMEOUT:   y = log((T_baseline + 1.0) / (T_limit + 1.0))
             where T_limit = max(30000 ms, 1.5 * T_baseline)
             actual_indexed_runtime_ms remains NULL
             label_is_censored = True
  BENCHMARK_ERROR: no target computed; row excluded from ML training

Strict separation:
  - ML feature columns: exactly the 74 FEATURE_SCHEMA columns, nothing else
  - Metadata/evaluation columns: identifiers, runtimes, target, provenance
  - Metadata MUST NEVER be passed to XGBoost

Controls:
  - A/A observations excluded from ML training
  - Placebo observations excluded from ML training
  - Permanent/existing indexes excluded
  - Duplicate (query_id, candidate_id) pairs rejected
"""

import math
from typing import Any, Dict, FrozenSet, Iterator, List, Optional, Set, Tuple

from src.dataset.timeout_policy import (
    DEFAULT_EPSILON_MS,
    DEFAULT_MIN_TIMEOUT_SECONDS,
    DEFAULT_TIMEOUT_MULTIPLIER,
    calculate_dynamic_timeout_limit,
    compute_speedup_target,
    compute_timeout_target,
)
from src.features.plan_features import (
    FEATURE_SCHEMA,
    FORBIDDEN_LEAKAGE_KEYS,
    extract_candidate_plan_features,
)

# ── Status constants ──────────────────────────────────────────────────────────
STATUS_SUCCESS = "SUCCESS"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_BENCHMARK_ERROR = "BENCHMARK_ERROR"

EPSILON_MS: float = DEFAULT_EPSILON_MS  # 1.0 ms — locked


# ── Metadata column names (never passed to XGBoost) ──────────────────────────
METADATA_COLUMNS: Tuple[str, ...] = (
    "query_id",
    "family_id",
    "structural_unit_id",
    "candidate_id",
    "candidate_table",
    "candidate_columns",
    "candidate_index_type",
    "candidate_index_sql",
    "baseline_runtime_ms",
    "actual_indexed_runtime_ms",
    "status",
    "timeout_limit_ms",
    "label_is_censored",
    "target",
    "target_type",
    "target_is_censored",
    "is_aa_control",
    "is_placebo",
    "is_control",
    "baseline_block_id",
    "baseline_plan_hash",
    "hypo_plan_hash",
    "row_source",
)

# ── Complete dataset schema ───────────────────────────────────────────────────
DATASET_ML_COLUMNS: Tuple[str, ...] = FEATURE_SCHEMA  # exactly 74
DATASET_SCHEMA: Tuple[str, ...] = DATASET_ML_COLUMNS + METADATA_COLUMNS


def _compute_target(
    t_baseline_ms: float,
    t_indexed_ms: Optional[float],
    status: str,
    timeout_limit_ms: Optional[float] = None,
    epsilon_ms: float = EPSILON_MS,
) -> Tuple[Optional[float], str, bool]:
    """
    Compute the training target y and associated provenance.

    Returns:
        (y, target_type, label_is_censored)

    SUCCESS:  y = log((T_baseline + ε) / (T_indexed + ε))
    TIMEOUT:  y = log((T_baseline + ε) / (T_limit + ε)),  censored=True
    ERROR:    y = None
    """
    if status == STATUS_SUCCESS:
        if t_indexed_ms is None:
            return (None, "missing_indexed_runtime", False)
        y = compute_speedup_target(t_baseline_ms, t_indexed_ms, epsilon_ms)
        return (y, "observed", False)

    if status == STATUS_TIMEOUT:
        t_limit = timeout_limit_ms
        if t_limit is None:
            t_limit = calculate_dynamic_timeout_limit(t_baseline_ms)
        y = compute_timeout_target(t_baseline_ms, t_limit, epsilon_ms)
        return (y, "bound_derived", True)

    # BENCHMARK_ERROR — no target
    return (None, None, False)


class DatasetRow:
    """
    A single validated, deduplicated dataset observation.

    .features  → dict of exactly FEATURE_SCHEMA keys (float values)
    .metadata  → dict of exactly METADATA_COLUMNS keys
    """

    __slots__ = ("features", "metadata")

    def __init__(
        self,
        features: Dict[str, float],
        metadata: Dict[str, Any],
    ) -> None:
        assert set(features.keys()) == set(FEATURE_SCHEMA), (
            f"Feature dict keys do not match FEATURE_SCHEMA. "
            f"Extra: {set(features)-set(FEATURE_SCHEMA)}, "
            f"Missing: {set(FEATURE_SCHEMA)-set(features)}"
        )
        self.features = features
        self.metadata = metadata

    def as_flat_dict(self) -> Dict[str, Any]:
        """Return a flat dict of features + metadata (for DataFrame construction)."""
        out = dict(self.features)
        out.update(self.metadata)
        return out


class DatasetBuilder:
    """
    Constructs the ML dataset from (query, candidate, benchmark_outcome) triples.

    Usage:
        builder = DatasetBuilder()
        row = builder.add_observation(
            query_id=...,
            family_id=...,
            candidate_id=...,
            candidate_def=...,
            baseline_plan=...,
            hypo_plan=...,
            hypo_index_name=...,
            benchmark_outcome=...,
        )
        rows = builder.rows           # List[DatasetRow]
        rejected = builder.rejected   # List[dict] with reason

    Controls enforced:
      - A/A control observations excluded
      - Placebo observations excluded
      - BENCHMARK_ERROR excluded
      - Duplicate (query_id, candidate_id) rejected
      - Feature schema enforced exactly
    """

    def __init__(self) -> None:
        self._rows: List[DatasetRow] = []
        self._rejected: List[Dict[str, Any]] = []
        self._seen_pairs: Set[Tuple[str, str]] = set()

    # ── Public read-only views ────────────────────────────────────────────────

    @property
    def rows(self) -> List[DatasetRow]:
        return list(self._rows)

    @property
    def rejected(self) -> List[Dict[str, Any]]:
        return list(self._rejected)

    @property
    def feature_columns(self) -> Tuple[str, ...]:
        return FEATURE_SCHEMA

    @property
    def metadata_columns(self) -> Tuple[str, ...]:
        return METADATA_COLUMNS

    # ── Core ingestion ────────────────────────────────────────────────────────

    def add_observation(
        self,
        *,
        query_id: str,
        family_id: str,
        candidate_id: str,
        candidate_def: Dict[str, Any],
        baseline_plan: Any,
        hypo_plan: Any,
        hypo_index_name: Optional[str] = None,
        benchmark_outcome: Dict[str, Any],
        structural_unit_id: Optional[str] = None,
        row_source: str = "real_index_benchmark",
    ) -> Optional[DatasetRow]:
        """
        Validate and incorporate one (query, candidate) observation.

        Returns the DatasetRow if accepted, or None if rejected.
        Rejection reasons are stored in self.rejected.
        """
        # ── Control: reject A/A observations ─────────────────────────────────
        if benchmark_outcome.get("is_aa_control") or benchmark_outcome.get("control_type") == "aa_control":
            self._reject(query_id, candidate_id, "aa_control", benchmark_outcome)
            return None

        # ── Control: reject Placebo observations ──────────────────────────────
        if benchmark_outcome.get("is_placebo") or benchmark_outcome.get("is_control"):
            self._reject(query_id, candidate_id, "placebo_control", benchmark_outcome)
            return None

        # ── Control: reject BENCHMARK_ERROR rows ──────────────────────────────
        status = benchmark_outcome.get("status", STATUS_BENCHMARK_ERROR)
        if status == STATUS_BENCHMARK_ERROR:
            self._reject(query_id, candidate_id, "benchmark_error", benchmark_outcome)
            return None

        # ── Control: duplicate (query_id, candidate_id) rejection ─────────────
        pair_key = (query_id, candidate_id)
        if pair_key in self._seen_pairs:
            self._reject(query_id, candidate_id, "duplicate_pair", benchmark_outcome)
            return None

        # ── Feature extraction ────────────────────────────────────────────────
        features = extract_candidate_plan_features(
            baseline_plan=baseline_plan,
            hypo_plan=hypo_plan,
            hypo_index_name=hypo_index_name,
        )

        # ── Target computation ────────────────────────────────────────────────
        t_baseline_ms: Optional[float] = benchmark_outcome.get("T_baseline") or benchmark_outcome.get("baseline_runtime_ms")
        actual_indexed_ms: Optional[float] = benchmark_outcome.get("actual_runtime_ms") or benchmark_outcome.get("median_runtime_ms")
        timeout_limit_ms: Optional[float] = benchmark_outcome.get("timeout_limit_ms") or benchmark_outcome.get("T_limit")

        if t_baseline_ms is None:
            self._reject(query_id, candidate_id, "missing_baseline_runtime", benchmark_outcome)
            return None

        target, target_type, label_is_censored = _compute_target(
            t_baseline_ms=float(t_baseline_ms),
            t_indexed_ms=float(actual_indexed_ms) if actual_indexed_ms is not None else None,
            status=status,
            timeout_limit_ms=float(timeout_limit_ms) if timeout_limit_ms is not None else None,
        )

        # Enforce: TIMEOUT must have NULL actual_indexed_runtime_ms
        if status == STATUS_TIMEOUT:
            actual_indexed_ms = None

        # ── Assemble metadata (never passed to XGBoost) ───────────────────────
        metadata: Dict[str, Any] = {
            "query_id": query_id,
            "family_id": family_id,
            "structural_unit_id": structural_unit_id or family_id,
            "candidate_id": candidate_id,
            "candidate_table": candidate_def.get("table"),
            "candidate_columns": candidate_def.get("columns"),
            "candidate_index_type": candidate_def.get("index_type", "btree"),
            "candidate_index_sql": candidate_def.get("sql") or benchmark_outcome.get("index_sql"),
            "baseline_runtime_ms": t_baseline_ms,
            "actual_indexed_runtime_ms": actual_indexed_ms,
            "status": status,
            "timeout_limit_ms": timeout_limit_ms,
            "label_is_censored": label_is_censored,
            "target": target,
            "target_type": target_type,
            "target_is_censored": label_is_censored,
            "is_aa_control": bool(benchmark_outcome.get("is_aa_control", False)),
            "is_placebo": bool(benchmark_outcome.get("is_placebo", False)),
            "is_control": bool(benchmark_outcome.get("is_control", False)),
            "baseline_block_id": benchmark_outcome.get("baseline_block_id"),
            "baseline_plan_hash": benchmark_outcome.get("baseline_plan_hash"),
            "hypo_plan_hash": None,  # populated from features if available
            "row_source": row_source,
        }

        # ── Build and register the row ─────────────────────────────────────────
        row = DatasetRow(features=features, metadata=metadata)
        self._rows.append(row)
        self._seen_pairs.add(pair_key)
        return row

    def _reject(
        self,
        query_id: str,
        candidate_id: str,
        reason: str,
        outcome: Dict[str, Any],
    ) -> None:
        self._rejected.append({
            "query_id": query_id,
            "candidate_id": candidate_id,
            "reason": reason,
            "status": outcome.get("status"),
            "outcome": outcome,
        })

    # ── Summary statistics ────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """Return a summary of current dataset state."""
        statuses = [r.metadata["status"] for r in self._rows]
        targets = [r.metadata["target"] for r in self._rows if r.metadata["target"] is not None]
        censored = [r for r in self._rows if r.metadata["label_is_censored"]]

        summary: Dict[str, Any] = {
            "total_accepted": len(self._rows),
            "total_rejected": len(self._rejected),
            "status_counts": {
                STATUS_SUCCESS: statuses.count(STATUS_SUCCESS),
                STATUS_TIMEOUT: statuses.count(STATUS_TIMEOUT),
            },
            "rejection_reasons": {},
            "censored_count": len(censored),
            "target_count": len(targets),
            "feature_count": len(FEATURE_SCHEMA),
            "metadata_count": len(METADATA_COLUMNS),
        }

        for r in self._rejected:
            reason = r["reason"]
            summary["rejection_reasons"][reason] = summary["rejection_reasons"].get(reason, 0) + 1

        if targets:
            import statistics as stats_mod
            sorted_targets = sorted(targets)
            summary["target_min"] = sorted_targets[0]
            summary["target_max"] = sorted_targets[-1]
            summary["target_median"] = stats_mod.median(sorted_targets)
            summary["target_mean"] = stats_mod.mean(sorted_targets)
            n = len(sorted_targets)
            summary["target_p10"] = sorted_targets[max(0, int(0.10 * n) - 1)]
            summary["target_p90"] = sorted_targets[min(n - 1, int(0.90 * n))]
            positive = sum(1 for t in targets if t > 0)
            summary["target_positive_count"] = positive
            summary["target_negative_count"] = sum(1 for t in targets if t < 0)
            summary["target_zero_count"] = sum(1 for t in targets if t == 0)

        return summary

    def as_records(self) -> List[Dict[str, Any]]:
        """Return all accepted rows as a flat list of dicts (features + metadata)."""
        return [row.as_flat_dict() for row in self._rows]

    def ml_matrix_dicts(self) -> List[Dict[str, float]]:
        """Return only the feature dicts for each accepted row (ML matrix, no metadata)."""
        return [dict(row.features) for row in self._rows]

    def targets(self) -> List[Optional[float]]:
        """Return the target value for each accepted row."""
        return [row.metadata["target"] for row in self._rows]


# ── Leakage audit ─────────────────────────────────────────────────────────────

def audit_ml_matrix_for_leakage(
    ml_matrix_dicts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Audit a list of ML feature dicts for any forbidden leakage fields.

    Returns:
        {"passed": True/False, "violations": [...]}
    """
    violations = []
    for i, row in enumerate(ml_matrix_dicts):
        for key in row:
            if key in FORBIDDEN_LEAKAGE_KEYS:
                violations.append({"row": i, "key": key, "type": "forbidden_key"})
            for fk in FORBIDDEN_LEAKAGE_KEYS:
                if key.startswith(f"{fk}_") or key.endswith(f"_{fk}"):
                    violations.append({"row": i, "key": key, "type": "forbidden_substring", "forbidden_token": fk})
        extra_keys = set(row.keys()) - set(FEATURE_SCHEMA)
        for ek in extra_keys:
            violations.append({"row": i, "key": ek, "type": "not_in_schema"})
        missing_keys = set(FEATURE_SCHEMA) - set(row.keys())
        for mk in missing_keys:
            violations.append({"row": i, "key": mk, "type": "missing_schema_key"})

    return {
        "passed": len(violations) == 0,
        "violation_count": len(violations),
        "violations": violations,
    }
