"""
Stage 3: Final Model Training and Holdout Evaluation
=====================================================
Frozen protocol. Do NOT modify this script after test-set evaluation begins.
Do NOT retrain after seeing results.
Do NOT change metric definitions, hyperparameters, or ranking signals.
"""

import json
import os
import sys
import random
import math
import numpy as np
import pandas as pd
import xgboost as xgb
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from data_loader import load_and_preprocess_data, split_data

# ─────────────────────────────────────────────────────────────
# FROZEN CONSTANTS — DO NOT MODIFY
# ─────────────────────────────────────────────────────────────

FEATURES = [
    'baseline_total_cost', 'baseline_startup_cost', 'baseline_plan_rows', 'baseline_plan_width', 'baseline_plan_depth', 'baseline_total_node_count',
    'hypo_total_cost', 'hypo_startup_cost', 'hypo_plan_rows', 'hypo_plan_width', 'hypo_plan_depth', 'hypo_total_node_count',
    'total_cost_delta', 'startup_cost_delta', 'plan_rows_delta', 'plan_width_delta', 'plan_depth_delta', 'node_count_delta',
    'baseline_seq_scan_count', 'hypo_seq_scan_count', 'seq_scan_count_delta',
    'baseline_index_scan_count', 'hypo_index_scan_count', 'index_scan_count_delta',
    'baseline_index_only_scan_count', 'hypo_index_only_scan_count', 'index_only_scan_count_delta',
    'baseline_bitmap_heap_scan_count', 'hypo_bitmap_heap_scan_count', 'bitmap_heap_scan_count_delta',
    'baseline_bitmap_index_scan_count', 'hypo_bitmap_index_scan_count', 'bitmap_index_scan_count_delta',
    'baseline_tid_scan_count', 'hypo_tid_scan_count', 'tid_scan_count_delta',
    'baseline_nested_loop_count', 'hypo_nested_loop_count', 'nested_loop_count_delta',
    'baseline_hash_join_count', 'hypo_hash_join_count', 'hash_join_count_delta',
    'baseline_merge_join_count', 'hypo_merge_join_count', 'merge_join_count_delta',
    'baseline_sort_count', 'hypo_sort_count', 'sort_count_delta',
    'baseline_incremental_sort_count', 'hypo_incremental_sort_count', 'incremental_sort_count_delta',
    'baseline_aggregate_count', 'hypo_aggregate_count', 'aggregate_count_delta',
    'baseline_hash_count', 'hypo_hash_count', 'hash_count_delta',
    'baseline_materialize_count', 'hypo_materialize_count', 'materialize_count_delta',
    'baseline_memoize_count', 'hypo_memoize_count', 'memoize_count_delta',
    'baseline_gather_count', 'hypo_gather_count', 'gather_count_delta',
    'baseline_gather_merge_count', 'hypo_gather_merge_count', 'gather_merge_count_delta',
    'plan_changed', 'scan_structure_changed', 'join_structure_changed',
    'candidate_used_in_hypo_plan', 'candidate_unused_in_hypo_plan',
]

BEST_PARAMS = dict(
    max_depth=2,
    min_child_weight=2,
    learning_rate=0.1,
    n_estimators=200,
    subsample=1.0,
    colsample_bytree=0.6,
    reg_lambda=1.0,
    random_state=42,
)

LEAKAGE_COLS = [
    'target', 'baseline_runtime_ms', 'actual_indexed_runtime_ms',
    'query_id', 'candidate_id', 'family_id', 'structural_unit_id',
    'candidate_table', 'candidate_columns', 'candidate_index_type',
    'candidate_index_sql', 'baseline_plan_hash', 'hypo_plan_hash',
]

RANDOM_SEED_SUFFIX = 42  # frozen


# ─────────────────────────────────────────────────────────────
# METRIC IMPLEMENTATIONS — FROZEN DEFINITIONS
# ─────────────────────────────────────────────────────────────

def compute_ndcg3(df_query: pd.DataFrame, score_col: str, ascending: bool = False) -> float:
    """
    Compute NDCG@3 for a single query.
    Relevance = max(0, actual_y).
    If IDCG@3 == 0 → NDCG@3 = 1.0.
    Tie-break on candidate_id ASC always.
    score_col: column used to rank candidates.
    ascending: True means lower score = higher rank (for HypoPG).
    """
    df = df_query.copy()
    df['relevance'] = df['target'].clip(lower=0.0)

    # Method ranking
    df_pred = df.sort_values(
        by=[score_col, 'candidate_id'],
        ascending=[ascending, True]
    ).head(3)
    dcg = sum(
        rel / math.log2(pos + 2)
        for pos, rel in enumerate(df_pred['relevance'])
    )

    # Ideal ranking: relevance DESC, candidate_id ASC
    df_ideal = df.sort_values(
        by=['relevance', 'candidate_id'],
        ascending=[False, True]
    ).head(3)
    idcg = sum(
        rel / math.log2(pos + 2)
        for pos, rel in enumerate(df_ideal['relevance'])
    )

    if idcg == 0.0:
        return 1.0
    return dcg / idcg


def compute_deterministic_spearman(df_query: pd.DataFrame, score_col: str, ascending: bool = False) -> float | None:
    """
    Compute deterministic Spearman for a single query.
    Returns None if the query is degenerate (< 2 candidates, or all actual_y identical).
    Uses explicit integer rank arrays (tied-correctly using frozen deterministic sort).
    Pearson correlation of those two rank arrays = Spearman.
    """
    df = df_query.copy().reset_index(drop=True)
    n = len(df)

    if n < 2:
        return None
    if df['target'].max() == df['target'].min():
        return None

    # Method ranks: 1 = best
    df_method = df.sort_values(by=[score_col, 'candidate_id'], ascending=[ascending, True])
    method_ranks = pd.Series(
        range(1, n + 1), index=df_method.index, dtype=float
    )

    # Ground-truth ranks: 1 = best (highest actual_y)
    df_gt = df.sort_values(by=['target', 'candidate_id'], ascending=[False, True])
    gt_ranks = pd.Series(
        range(1, n + 1), index=df_gt.index, dtype=float
    )

    # Align by original index
    m_arr = method_ranks.reindex(df.index).values
    g_arr = gt_ranks.reindex(df.index).values

    # Pearson on rank arrays = Spearman
    if np.std(m_arr) == 0 or np.std(g_arr) == 0:
        return None  # constant rank array → undefined correlation

    corr = float(np.corrcoef(m_arr, g_arr)[0, 1])
    return corr


def compute_top1_regret(df_query: pd.DataFrame, score_col: str, ascending: bool = False) -> float:
    """
    Compute top-1 regret for a single query.
    Regret_q = max(actual_y) - actual_y of top-1 ranked candidate.
    Units: log-benefit. Lower is better. Always >= 0.
    """
    df = df_query.copy()
    best = df['target'].max()

    df_pred = df.sort_values(
        by=[score_col, 'candidate_id'],
        ascending=[ascending, True]
    )
    top1_actual = float(df_pred.iloc[0]['target'])
    return float(best - top1_actual)


def compute_random_ndcg3(df_query: pd.DataFrame, query_id: str) -> float:
    """NDCG@3 for random ranking. Per-query deterministic RNG."""
    df = df_query.copy()
    df['relevance'] = df['target'].clip(lower=0.0)

    candidates = list(df.index)
    rng = random.Random(f"{query_id}_{RANDOM_SEED_SUFFIX}")
    rng.shuffle(candidates)
    ranked = candidates[:3]

    dcg = sum(
        df.loc[idx, 'relevance'] / math.log2(pos + 2)
        for pos, idx in enumerate(ranked)
    )

    df_ideal = df.sort_values(by=['relevance', 'candidate_id'], ascending=[False, True]).head(3)
    idcg = sum(
        rel / math.log2(pos + 2)
        for pos, rel in enumerate(df_ideal['relevance'])
    )

    if idcg == 0.0:
        return 1.0
    return dcg / idcg


def compute_random_spearman(df_query: pd.DataFrame, query_id: str) -> float | None:
    """Deterministic Spearman for random ranking."""
    df = df_query.copy().reset_index(drop=True)
    n = len(df)

    if n < 2:
        return None
    if df['target'].max() == df['target'].min():
        return None

    candidates = list(df.index)
    rng = random.Random(f"{query_id}_{RANDOM_SEED_SUFFIX}")
    rng.shuffle(candidates)
    method_ranks = pd.Series(
        {idx: rank for rank, idx in enumerate(candidates, start=1)},
        dtype=float
    ).reindex(df.index)

    df_gt = df.sort_values(by=['target', 'candidate_id'], ascending=[False, True])
    gt_ranks = pd.Series(
        range(1, n + 1), index=df_gt.index, dtype=float
    ).reindex(df.index)

    m_arr = method_ranks.values
    g_arr = gt_ranks.values

    if np.std(m_arr) == 0 or np.std(g_arr) == 0:
        return None

    return float(np.corrcoef(m_arr, g_arr)[0, 1])


def compute_random_regret(df_query: pd.DataFrame, query_id: str) -> float:
    """Top-1 regret for random ranking."""
    df = df_query.copy()
    best = df['target'].max()

    candidates = list(df.index)
    rng = random.Random(f"{query_id}_{RANDOM_SEED_SUFFIX}")
    rng.shuffle(candidates)
    top1_actual = float(df.loc[candidates[0], 'target'])
    return float(best - top1_actual)


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def run():
    timestamp = datetime.now().isoformat()
    print("=" * 60)
    print("Stage 3: Final Training and Holdout Evaluation")
    print(f"Timestamp: {timestamp}")
    print("=" * 60)

    # ── 1. Load data ──────────────────────────────────────────
    print("\n[1/5] Loading and splitting data...")
    json_path = 'experiments/final_benchmark_results.json'
    csv_path  = 'experiments/job_similarity_components.csv'

    rows, mapping = load_and_preprocess_data(json_path, csv_path)
    train_rows, test_rows = split_data(rows, test_size=0.2, random_state=42)

    # ── 2. Pre-training integrity checks ──────────────────────
    print("[2/5] Running pre-training integrity checks...")

    assert len(train_rows) == 371, f"FAIL: Expected 371 train rows, got {len(train_rows)}"
    assert len(test_rows)  == 228, f"FAIL: Expected 228 test rows, got {len(test_rows)}"

    train_units = set(r['structural_unit_id'] for r in train_rows)
    test_units  = set(r['structural_unit_id'] for r in test_rows)

    assert not train_units & test_units, "FAIL: Train/test structural unit overlap!"
    assert len(train_units) == 16, f"FAIL: Expected 16 train structural units, got {len(train_units)}"
    assert len(test_units)  ==  4, f"FAIL: Expected 4 test structural units, got {len(test_units)}"
    assert len(FEATURES) == 74, f"FAIL: Expected 74 features, got {len(FEATURES)}"

    for col in LEAKAGE_COLS:
        assert col not in FEATURES, f"FAIL: Leakage column '{col}' in feature list!"

    # Build training dataframe — test set NOT touched yet
    df_train = pd.DataFrame(train_rows)
    if 'target' not in df_train.columns:
        df_train['target'] = np.log(
            (df_train['baseline_runtime_ms'] + 1) /
            (df_train['actual_indexed_runtime_ms'] + 1)
        )

    for col in ['plan_changed', 'scan_structure_changed', 'join_structure_changed',
                'candidate_used_in_hypo_plan', 'candidate_unused_in_hypo_plan']:
        df_train[col] = df_train[col].astype(np.float32)

    X_train = df_train[FEATURES].astype(np.float32)
    y_train = df_train['target'].astype(np.float64)

    assert X_train.shape == (371, 74), f"FAIL: X_train shape {X_train.shape}"
    assert np.all(np.isfinite(X_train.values)), "FAIL: Non-finite values in X_train"
    assert np.all(np.isfinite(y_train.values)), "FAIL: Non-finite values in y_train"

    # No controls in training set
    assert not any(df_train['is_control']), "FAIL: Control rows found in training data"

    print("    All pre-training integrity checks passed.")

    # ── 3. Train final model ──────────────────────────────────
    print("\n[3/5] Training final XGBoost model on 371 training rows...")
    final_model = xgb.XGBRegressor(**BEST_PARAMS)
    final_model.fit(X_train, y_train)
    print("    Model training complete. Model is now FROZEN.")

    # Save model artifact
    os.makedirs('experiments', exist_ok=True)
    model_path = 'experiments/final_xgb_model.json'
    if not os.path.exists(model_path):
        final_model.save_model(model_path)
        print(f"    Model saved to {model_path}")
    else:
        print(f"    WARNING: {model_path} already exists — skipping save to avoid overwrite.")

    # ── 4. Prepare test set ───────────────────────────────────
    print("\n[4/5] Preparing holdout test set...")
    df_test = pd.DataFrame(test_rows)
    if 'target' not in df_test.columns:
        df_test['target'] = np.log(
            (df_test['baseline_runtime_ms'] + 1) /
            (df_test['actual_indexed_runtime_ms'] + 1)
        )

    for col in ['plan_changed', 'scan_structure_changed', 'join_structure_changed',
                'candidate_used_in_hypo_plan', 'candidate_unused_in_hypo_plan']:
        df_test[col] = df_test[col].astype(np.float32)

    X_test = df_test[FEATURES].astype(np.float32)

    assert X_test.shape == (228, 74), f"FAIL: X_test shape {X_test.shape}"
    assert np.all(np.isfinite(X_test.values)),  "FAIL: Non-finite values in X_test"
    assert np.all(np.isfinite(df_test['target'].values)), "FAIL: Non-finite target in test"

    # Generate XGBoost predictions
    df_test = df_test.copy()
    df_test['xgb_predicted_y'] = final_model.predict(X_test).astype(np.float64)

    # Fair-comparison check: all methods see the same rows
    assert df_test['query_id'].notna().all(), "FAIL: null query_id in test set"
    assert df_test['candidate_id'].notna().all(), "FAIL: null candidate_id in test set"
    assert df_test['hypo_total_cost'].notna().all(), "FAIL: null hypo_total_cost in test set"
    assert np.all(np.isfinite(df_test['hypo_total_cost'].values)), "FAIL: non-finite hypo_total_cost"

    query_ids = sorted(df_test['query_id'].unique())
    n_queries = len(query_ids)
    print(f"    Holdout: {len(df_test)} rows, {n_queries} queries, {len(test_units)} structural units")

    # ── 5. Evaluate all three methods ─────────────────────────
    print("\n[5/5] Evaluating XGBoost, HypoPG, Random on holdout...")

    xgb_ndcg, xgb_spearman, xgb_regret = [], [], []
    hypo_ndcg, hypo_spearman, hypo_regret = [], [], []
    rand_ndcg, rand_spearman, rand_regret = [], [], []

    xgb_spearman_excluded, hypo_spearman_excluded, rand_spearman_excluded = [], [], []

    per_query_results = []

    for q_id in query_ids:
        df_q = df_test[df_test['query_id'] == q_id].copy()

        # ── NDCG@3 ──────────────────────────────────────────
        xgb_n  = compute_ndcg3(df_q, 'xgb_predicted_y', ascending=False)
        hypo_n = compute_ndcg3(df_q, 'hypo_total_cost',  ascending=True)
        rand_n = compute_random_ndcg3(df_q, q_id)

        xgb_ndcg.append(xgb_n)
        hypo_ndcg.append(hypo_n)
        rand_ndcg.append(rand_n)

        # ── Spearman ─────────────────────────────────────────
        xgb_s  = compute_deterministic_spearman(df_q, 'xgb_predicted_y', ascending=False)
        hypo_s = compute_deterministic_spearman(df_q, 'hypo_total_cost',  ascending=True)
        rand_s = compute_random_spearman(df_q, q_id)

        if xgb_s is None:
            xgb_spearman_excluded.append(q_id)
        else:
            xgb_spearman.append(xgb_s)

        if hypo_s is None:
            hypo_spearman_excluded.append(q_id)
        else:
            hypo_spearman.append(hypo_s)

        if rand_s is None:
            rand_spearman_excluded.append(q_id)
        else:
            rand_spearman.append(rand_s)

        # ── Regret ───────────────────────────────────────────
        xgb_r  = compute_top1_regret(df_q, 'xgb_predicted_y', ascending=False)
        hypo_r = compute_top1_regret(df_q, 'hypo_total_cost',  ascending=True)
        rand_r = compute_random_regret(df_q, q_id)

        xgb_regret.append(xgb_r)
        hypo_regret.append(hypo_r)
        rand_regret.append(rand_r)

        per_query_results.append({
            'query_id': q_id,
            'n_candidates': len(df_q),
            'best_actual_y': float(df_q['target'].max()),
            'xgb':  {'ndcg3': xgb_n,  'regret': xgb_r,  'spearman': xgb_s},
            'hypopg': {'ndcg3': hypo_n, 'regret': hypo_r, 'spearman': hypo_s},
            'random': {'ndcg3': rand_n, 'regret': rand_r, 'spearman': rand_s},
        })

    # ── Macro aggregation ─────────────────────────────────────
    macro = lambda lst: float(np.mean(lst)) if lst else float('nan')

    xgb_macro_ndcg  = macro(xgb_ndcg)
    hypo_macro_ndcg = macro(hypo_ndcg)
    rand_macro_ndcg = macro(rand_ndcg)

    xgb_macro_spearman  = macro(xgb_spearman)
    hypo_macro_spearman = macro(hypo_spearman)
    rand_macro_spearman = macro(rand_spearman)

    xgb_macro_regret  = macro(xgb_regret)
    hypo_macro_regret = macro(hypo_regret)
    rand_macro_regret = macro(rand_regret)

    # ── Differences (XGBoost - comparator) ───────────────────
    ndcg_vs_hypo  = xgb_macro_ndcg - hypo_macro_ndcg
    ndcg_vs_rand  = xgb_macro_ndcg - rand_macro_ndcg
    spm_vs_hypo   = xgb_macro_spearman - hypo_macro_spearman
    spm_vs_rand   = xgb_macro_spearman - rand_macro_spearman
    reg_vs_hypo   = xgb_macro_regret - hypo_macro_regret   # negative = XGB better
    reg_vs_rand   = xgb_macro_regret - rand_macro_regret

    # ── Print summary ─────────────────────────────────────────
    print("\n" + "=" * 60)
    print("FINAL EVALUATION RESULTS")
    print("=" * 60)
    print(f"\n{'Metric':<28} {'XGBoost':>10} {'HypoPG':>10} {'Random':>10}")
    print("-" * 62)
    print(f"{'Macro NDCG@3':<28} {xgb_macro_ndcg:>10.4f} {hypo_macro_ndcg:>10.4f} {rand_macro_ndcg:>10.4f}")
    print(f"{'Macro Spearman':<28} {xgb_macro_spearman:>10.4f} {hypo_macro_spearman:>10.4f} {rand_macro_spearman:>10.4f}")
    print(f"{'Macro Top-1 Regret':<28} {xgb_macro_regret:>10.4f} {hypo_macro_regret:>10.4f} {rand_macro_regret:>10.4f}")
    print(f"\nSpearman eligible queries : XGB={len(xgb_spearman)}, HypoPG={len(hypo_spearman)}, Random={len(rand_spearman)}")
    print(f"Spearman excluded queries : XGB={len(xgb_spearman_excluded)}, HypoPG={len(hypo_spearman_excluded)}, Random={len(rand_spearman_excluded)}")
    print(f"\nXGBoost vs HypoPG  NDCG    : {ndcg_vs_hypo:+.4f}")
    print(f"XGBoost vs Random  NDCG    : {ndcg_vs_rand:+.4f}")
    print(f"XGBoost vs HypoPG  Spearman: {spm_vs_hypo:+.4f}")
    print(f"XGBoost vs Random  Spearman: {spm_vs_rand:+.4f}")
    print(f"XGBoost vs HypoPG  Regret  : {reg_vs_hypo:+.4f}  (negative = XGB lower regret = better)")
    print(f"XGBoost vs Random  Regret  : {reg_vs_rand:+.4f}  (negative = XGB lower regret = better)")

    # ── Build output JSON ─────────────────────────────────────
    results = {
        'metadata': {
            'timestamp': timestamp,
            'stage': 'Stage 3 — Final Evaluation',
            'protocol_frozen': True,
            'post_test_modification': False,
        },
        'final_model_configuration': {
            'model_type': 'XGBRegressor',
            **BEST_PARAMS,
            'trained_on_rows': 371,
            'no_early_stopping': True,
            'no_post_test_retraining': True,
        },
        'data_split': {
            'total_accepted_rows': 599,
            'train_rows': 371,
            'test_rows': 228,
            'train_structural_units': sorted(list(train_units)),
            'test_structural_units': sorted(list(test_units)),
            'n_train_structural_units': 16,
            'n_test_structural_units': 4,
            'split_random_state': 42,
            'split_method': 'GroupShuffleSplit(structural_unit_id)',
        },
        'features': {
            'count': 74,
            'names': FEATURES,
        },
        'target_definition': 'y = log((T_baseline + 1) / (T_indexed + 1))',
        'evaluation': {
            'n_test_queries': n_queries,
            'query_ids': query_ids,
            'xgboost': {
                'ranking_signal': 'xgb_predicted_y DESC, candidate_id ASC',
                'macro_ndcg3': xgb_macro_ndcg,
                'macro_spearman': xgb_macro_spearman,
                'spearman_eligible_queries': len(xgb_spearman),
                'spearman_excluded_queries': len(xgb_spearman_excluded),
                'spearman_excluded_query_ids': xgb_spearman_excluded,
                'macro_top1_regret': xgb_macro_regret,
            },
            'hypopg': {
                'ranking_signal': 'hypo_total_cost ASC, candidate_id ASC',
                'macro_ndcg3': hypo_macro_ndcg,
                'macro_spearman': hypo_macro_spearman,
                'spearman_eligible_queries': len(hypo_spearman),
                'spearman_excluded_queries': len(hypo_spearman_excluded),
                'spearman_excluded_query_ids': hypo_spearman_excluded,
                'macro_top1_regret': hypo_macro_regret,
            },
            'random': {
                'ranking_signal': f'random.Random(f"{{query_id}}_{RANDOM_SEED_SUFFIX}").shuffle(candidates)',
                'random_seed_suffix': RANDOM_SEED_SUFFIX,
                'macro_ndcg3': rand_macro_ndcg,
                'macro_spearman': rand_macro_spearman,
                'spearman_eligible_queries': len(rand_spearman),
                'spearman_excluded_queries': len(rand_spearman_excluded),
                'spearman_excluded_query_ids': rand_spearman_excluded,
                'macro_top1_regret': rand_macro_regret,
            },
            'comparisons': {
                'note': 'difference = XGBoost - comparator; for regret lower is better',
                'xgb_vs_hypopg_ndcg3': ndcg_vs_hypo,
                'xgb_vs_random_ndcg3': ndcg_vs_rand,
                'xgb_vs_hypopg_spearman': spm_vs_hypo,
                'xgb_vs_random_spearman': spm_vs_rand,
                'xgb_vs_hypopg_regret': reg_vs_hypo,
                'xgb_vs_random_regret': reg_vs_rand,
            },
        },
        'metric_definitions': {
            'ndcg3': {
                'relevance': 'max(0, actual_y)',
                'ranking_cutoff': 3,
                'idcg_zero_handling': 'NDCG@3 = 1.0',
                'aggregation': 'macro (mean across queries)',
            },
            'spearman': {
                'method': 'Pearson correlation on explicit deterministic integer rank arrays',
                'prediction_rank_order': 'method score DESC, candidate_id ASC',
                'ground_truth_rank_order': 'actual_y DESC, candidate_id ASC',
                'exclusion_criteria': 'n_candidates < 2 OR all actual_y identical OR constant rank array',
                'aggregation': 'macro (mean across eligible queries)',
            },
            'top1_regret': {
                'formula': 'max(actual_y) - actual_y_of_top1_candidate',
                'units': 'log-benefit (lower is better)',
                'interpretation': 'log(T_selected / T_optimal)',
                'aggregation': 'macro (mean across queries)',
            },
        },
        'per_query_results': per_query_results,
        'integrity_checks': {
            'train_rows_verified': 371,
            'test_rows_verified': 228,
            'train_structural_units_verified': 16,
            'test_structural_units_verified': 4,
            'train_test_unit_overlap': False,
            'feature_count_verified': 74,
            'leakage_columns_excluded': True,
            'finite_features_verified': True,
            'finite_target_verified': True,
            'controls_excluded': True,
            'test_set_untouched_before_training': True,
            'no_post_test_modification': True,
            'identical_candidate_sets_for_all_methods': True,
        },
        'holdout_isolation_confirmation': (
            'The 228-row structural holdout was not used for feature selection, '
            'hyperparameter selection, model training, preprocessing, or protocol design. '
            'It was accessed once, after the model was fully trained and frozen, '
            'for this final one-shot evaluation.'
        ),
    }

    # ── Save results ──────────────────────────────────────────
    results_path = 'experiments/final_evaluation_results.json'
    if os.path.exists(results_path):
        print(f"\nWARNING: {results_path} already exists. Skipping save to protect existing artifact.")
    else:
        with open(results_path, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to {results_path}")

    print("\n[DONE] Stage 3 complete. Do NOT retrain or re-evaluate.")
    return results


if __name__ == '__main__':
    run()
