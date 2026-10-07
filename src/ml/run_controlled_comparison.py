"""
Controlled Model Comparison Experiment
======================================
Evaluates pre-specified models and feature sets using Leave-One-Structural-Unit-Out
Cross-Validation (16 folds) on ONLY the 371-row development dataset.

NON-NEGOTIABLE SAFETY RULES:
- The 228-row frozen holdout is NOT used for training, feature selection,
  hyperparameter tuning, model selection, or decision rules.
- Existing benchmark and evaluation artifacts are strictly preserved.
"""

import json
import os
import sys
import math
import random
import numpy as np
import pandas as pd
import xgboost as xgb
from datetime import datetime
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_squared_error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_loader import load_and_preprocess_data, split_data

# ─────────────────────────────────────────────────────────────
# FEATURES
# ─────────────────────────────────────────────────────────────

FEATURES_74 = [
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

# 25 constant features identified in dev (std == 0.0)
CONSTANT_FEATURES = [
    'baseline_plan_rows', 'hypo_plan_rows', 'plan_rows_delta', 'plan_width_delta',
    'baseline_tid_scan_count', 'hypo_tid_scan_count', 'tid_scan_count_delta',
    'baseline_merge_join_count', 'hypo_merge_join_count', 'merge_join_count_delta',
    'baseline_sort_count', 'hypo_sort_count', 'sort_count_delta',
    'baseline_incremental_sort_count', 'hypo_incremental_sort_count', 'incremental_sort_count_delta',
    'baseline_aggregate_count', 'hypo_aggregate_count', 'aggregate_count_delta',
    'baseline_gather_count', 'hypo_gather_count', 'gather_count_delta',
    'baseline_gather_merge_count', 'hypo_gather_merge_count', 'gather_merge_count_delta',
]

FEATURES_49 = [f for f in FEATURES_74 if f not in CONSTANT_FEATURES]

LEAKAGE_COLS = [
    'target', 'baseline_runtime_ms', 'actual_indexed_runtime_ms',
    'query_id', 'candidate_id', 'family_id', 'structural_unit_id',
    'candidate_table', 'candidate_columns', 'candidate_index_type',
    'candidate_index_sql', 'baseline_plan_hash', 'hypo_plan_hash',
]

RANDOM_SEED_SUFFIX = 42

# ─────────────────────────────────────────────────────────────
# FROZEN METRICS REUSED FROM PROTOCOL
# ─────────────────────────────────────────────────────────────

def compute_ndcg3(df_query: pd.DataFrame, score_col: str, ascending: bool = False) -> float:
    df = df_query.copy()
    df['relevance'] = df['target'].clip(lower=0.0)
    df_pred = df.sort_values(
        by=[score_col, 'candidate_id'],
        ascending=[ascending, True]
    ).head(3)
    dcg = sum(rel / math.log2(pos + 2) for pos, rel in enumerate(df_pred['relevance']))

    df_ideal = df.sort_values(
        by=['relevance', 'candidate_id'],
        ascending=[False, True]
    ).head(3)
    idcg = sum(rel / math.log2(pos + 2) for pos, rel in enumerate(df_ideal['relevance']))

    if idcg == 0.0:
        return 1.0
    return float(dcg / idcg)


def compute_deterministic_spearman(df_query: pd.DataFrame, score_col: str, ascending: bool = False) -> float | None:
    df = df_query.copy().reset_index(drop=True)
    n = len(df)
    if n < 2 or df['target'].max() == df['target'].min():
        return None

    df_method = df.sort_values(by=[score_col, 'candidate_id'], ascending=[ascending, True])
    method_ranks = pd.Series(range(1, n + 1), index=df_method.index, dtype=float)

    df_gt = df.sort_values(by=['target', 'candidate_id'], ascending=[False, True])
    gt_ranks = pd.Series(range(1, n + 1), index=df_gt.index, dtype=float)

    m_arr = method_ranks.reindex(df.index).values
    g_arr = gt_ranks.reindex(df.index).values

    if np.std(m_arr) == 0 or np.std(g_arr) == 0:
        return None
    return float(np.corrcoef(m_arr, g_arr)[0, 1])


def compute_top1_regret(df_query: pd.DataFrame, score_col: str, ascending: bool = False) -> float:
    df = df_query.copy()
    best = df['target'].max()
    df_pred = df.sort_values(
        by=[score_col, 'candidate_id'],
        ascending=[ascending, True]
    )
    top1_actual = float(df_pred.iloc[0]['target'])
    return float(best - top1_actual)


def compute_random_ndcg3(df_query: pd.DataFrame, query_id: str) -> float:
    df = df_query.copy()
    df['relevance'] = df['target'].clip(lower=0.0)
    candidates = list(df.index)
    rng = random.Random(f"{query_id}_{RANDOM_SEED_SUFFIX}")
    rng.shuffle(candidates)
    ranked = candidates[:3]

    dcg = sum(df.loc[idx, 'relevance'] / math.log2(pos + 2) for pos, idx in enumerate(ranked))
    df_ideal = df.sort_values(by=['relevance', 'candidate_id'], ascending=[False, True]).head(3)
    idcg = sum(rel / math.log2(pos + 2) for pos, rel in enumerate(df_ideal['relevance']))

    if idcg == 0.0:
        return 1.0
    return float(dcg / idcg)


def compute_random_spearman(df_query: pd.DataFrame, query_id: str) -> float | None:
    df = df_query.copy().reset_index(drop=True)
    n = len(df)
    if n < 2 or df['target'].max() == df['target'].min():
        return None

    candidates = list(df.index)
    rng = random.Random(f"{query_id}_{RANDOM_SEED_SUFFIX}")
    rng.shuffle(candidates)
    method_ranks = pd.Series(
        {idx: rank for rank, idx in enumerate(candidates, start=1)},
        dtype=float
    ).reindex(df.index)

    df_gt = df.sort_values(by=['target', 'candidate_id'], ascending=[False, True])
    gt_ranks = pd.Series(range(1, n + 1), index=df_gt.index, dtype=float).reindex(df.index)

    m_arr = method_ranks.values
    g_arr = gt_ranks.values
    if np.std(m_arr) == 0 or np.std(g_arr) == 0:
        return None
    return float(np.corrcoef(m_arr, g_arr)[0, 1])


def compute_random_regret(df_query: pd.DataFrame, query_id: str) -> float:
    df = df_query.copy()
    best = df['target'].max()
    candidates = list(df.index)
    rng = random.Random(f"{query_id}_{RANDOM_SEED_SUFFIX}")
    rng.shuffle(candidates)
    top1_actual = float(df.loc[candidates[0], 'target'])
    return float(best - top1_actual)


# ─────────────────────────────────────────────────────────────
# CONTROLLED EXPERIMENT EXECUTION
# ─────────────────────────────────────────────────────────────

def run_experiment():
    print("=" * 70)
    print("CONTROLLED MODEL COMPARISON EXPERIMENT")
    print("16-Fold Leave-One-Structural-Unit-Out Cross-Validation")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("=" * 70)

    # 1. Load data
    json_path = 'experiments/final_benchmark_results.json'
    csv_path  = 'experiments/job_similarity_components.csv'
    rows, mapping = load_and_preprocess_data(json_path, csv_path)
    train_rows, test_rows = split_data(rows, test_size=0.2, random_state=42)

    # Integrity Assertions
    assert len(train_rows) == 371, f"Expected 371 train rows, got {len(train_rows)}"
    assert len(test_rows) == 228, f"Expected 228 test rows, got {len(test_rows)}"

    df_train = pd.DataFrame(train_rows)
    if 'target' not in df_train.columns:
        df_train['target'] = np.log(
            (df_train['baseline_runtime_ms'] + 1) /
            (df_train['actual_indexed_runtime_ms'] + 1)
        )

    for col in ['plan_changed', 'scan_structure_changed', 'join_structure_changed',
                'candidate_used_in_hypo_plan', 'candidate_unused_in_hypo_plan']:
        df_train[col] = df_train[col].astype(np.float32)

    train_units = sorted(df_train['structural_unit_id'].unique())
    assert len(train_units) == 16, f"Expected 16 structural units, got {len(train_units)}"

    # Verify constant features in development
    for col in CONSTANT_FEATURES:
        assert df_train[col].std() == 0.0, f"Expected {col} to be constant, got std={df_train[col].std()}"

    print(f"\n[Data Verified] 371 rows across 16 structural units ({df_train['query_id'].nunique()} queries).")
    print(f"Feature Set A: {len(FEATURES_74)} features.")
    print(f"Feature Set B: {len(FEATURES_49)} non-constant features (25 constant features removed).")

    # Define model configurations
    models_to_run = [
        # Stage-2 XGBoost Reference
        {'id': 'xgb_stage2_74', 'name': 'XGBoost Stage-2 Reference (74 feat)', 'family': 'xgboost_stage2', 'feat': '74', 'features': FEATURES_74},
        {'id': 'xgb_stage2_49', 'name': 'XGBoost Stage-2 (49 clean feat)',     'family': 'xgboost_stage2', 'feat': '49', 'features': FEATURES_49},

        # Stage-1 XGBoost Baseline
        {'id': 'xgb_stage1_74', 'name': 'XGBoost Stage-1 Baseline (74 feat)',  'family': 'xgboost_stage1', 'feat': '74', 'features': FEATURES_74},
        {'id': 'xgb_stage1_49', 'name': 'XGBoost Stage-1 (49 clean feat)',     'family': 'xgboost_stage1', 'feat': '49', 'features': FEATURES_49},

        # Ridge Regression (alphas: 1.0, 10.0, 100.0)
        {'id': 'ridge_a1_74',   'name': 'Ridge alpha=1.0 (74 feat)',           'family': 'ridge', 'feat': '74', 'features': FEATURES_74, 'alpha': 1.0},
        {'id': 'ridge_a1_49',   'name': 'Ridge alpha=1.0 (49 clean feat)',     'family': 'ridge', 'feat': '49', 'features': FEATURES_49, 'alpha': 1.0},
        {'id': 'ridge_a10_74',  'name': 'Ridge alpha=10.0 (74 feat)',          'family': 'ridge', 'feat': '74', 'features': FEATURES_74, 'alpha': 10.0},
        {'id': 'ridge_a10_49',  'name': 'Ridge alpha=10.0 (49 clean feat)',    'family': 'ridge', 'feat': '49', 'features': FEATURES_49, 'alpha': 10.0},
        {'id': 'ridge_a100_74', 'name': 'Ridge alpha=100.0 (74 feat)',         'family': 'ridge', 'feat': '74', 'features': FEATURES_74, 'alpha': 100.0},
        {'id': 'ridge_a100_49', 'name': 'Ridge alpha=100.0 (49 clean feat)',   'family': 'ridge', 'feat': '49', 'features': FEATURES_49, 'alpha': 100.0},

        # XGBoost with Query-Demeaned Target
        {'id': 'xgb_demeaned_74', 'name': 'XGBoost Query-Demeaned (74 feat)',  'family': 'xgboost_demeaned', 'feat': '74', 'features': FEATURES_74},
        {'id': 'xgb_demeaned_49', 'name': 'XGBoost Query-Demeaned (49 feat)',  'family': 'xgboost_demeaned', 'feat': '49', 'features': FEATURES_49},

        # Baselines
        {'id': 'hypopg',        'name': 'HypoPG Planner (hypo_total_cost ASC)', 'family': 'baseline_hypopg'},
        {'id': 'random',        'name': 'Random Baseline (seed=42)',            'family': 'baseline_random'},
    ]

    # Structure to hold fold-level and unit-level results
    # results[model_id][fold_idx] = { ... }
    fold_results = {m['id']: [] for m in models_to_run}

    print("\nStarting Leave-One-Structural-Unit-Out Cross-Validation (16 folds)...")

    for fold_idx, held_out_unit in enumerate(train_units):
        val_mask = (df_train['structural_unit_id'] == held_out_unit)
        tr_mask = ~val_mask

        df_tr = df_train[tr_mask].copy()
        df_va = df_train[val_mask].copy()

        val_queries = sorted(df_va['query_id'].unique())
        n_val_queries = len(val_queries)
        n_val_rows = len(df_va)

        # ── Precompute Query Means for Demeaned Target (TRAINING SET ONLY) ──
        # Calculate mean(target) per query strictly within training fold
        train_query_means = df_tr.groupby('query_id')['target'].mean().to_dict()
        y_tr_demeaned = df_tr['target'] - df_tr['query_id'].map(train_query_means)
        global_train_target_mean = float(df_tr['target'].mean())

        # Evaluate each model on this fold
        for m in models_to_run:
            m_id = m['id']
            m_family = m['family']

            if m_family == 'baseline_hypopg':
                # HypoPG baseline
                ndcgs, spearmans, regrets = [], [], []
                for q_id in val_queries:
                    dq = df_va[df_va['query_id'] == q_id]
                    ndcgs.append(compute_ndcg3(dq, 'hypo_total_cost', ascending=True))
                    s = compute_deterministic_spearman(dq, 'hypo_total_cost', ascending=True)
                    if s is not None: spearmans.append(s)
                    regrets.append(compute_top1_regret(dq, 'hypo_total_cost', ascending=True))

                res = {
                    'fold': fold_idx + 1,
                    'held_out_unit': held_out_unit,
                    'val_queries': n_val_queries,
                    'val_rows': n_val_rows,
                    'ndcg3': float(np.mean(ndcgs)),
                    'spearman': float(np.mean(spearmans)) if spearmans else None,
                    'regret': float(np.mean(regrets)),
                    'rmse': None,
                    'query_ndcgs': {q: float(compute_ndcg3(df_va[df_va['query_id'] == q], 'hypo_total_cost', ascending=True)) for q in val_queries}
                }
                fold_results[m_id].append(res)

            elif m_family == 'baseline_random':
                # Random baseline
                ndcgs, spearmans, regrets = [], [], []
                q_ndcgs = {}
                for q_id in val_queries:
                    dq = df_va[df_va['query_id'] == q_id]
                    n = compute_random_ndcg3(dq, q_id)
                    ndcgs.append(n)
                    q_ndcgs[q_id] = n
                    s = compute_random_spearman(dq, q_id)
                    if s is not None: spearmans.append(s)
                    regrets.append(compute_random_regret(dq, q_id))

                res = {
                    'fold': fold_idx + 1,
                    'held_out_unit': held_out_unit,
                    'val_queries': n_val_queries,
                    'val_rows': n_val_rows,
                    'ndcg3': float(np.mean(ndcgs)),
                    'spearman': float(np.mean(spearmans)) if spearmans else None,
                    'regret': float(np.mean(regrets)),
                    'rmse': None,
                    'query_ndcgs': q_ndcgs
                }
                fold_results[m_id].append(res)

            elif m_family == 'ridge':
                feat_cols = m['features']
                # Fit scaler strictly on training data
                scaler = StandardScaler()
                X_tr = scaler.fit_transform(df_tr[feat_cols].astype(np.float64))
                X_va = scaler.transform(df_va[feat_cols].astype(np.float64))

                reg = Ridge(alpha=m['alpha'], random_state=42)
                reg.fit(X_tr, df_tr['target'].astype(np.float64))
                preds = reg.predict(X_va)

                df_va_eval = df_va.copy()
                df_va_eval['pred_score'] = preds
                rmse = float(np.sqrt(mean_squared_error(df_va_eval['target'], preds)))

                ndcgs, spearmans, regrets = [], [], []
                q_ndcgs = {}
                for q_id in val_queries:
                    dq = df_va_eval[df_va_eval['query_id'] == q_id]
                    n = compute_ndcg3(dq, 'pred_score', ascending=False)
                    ndcgs.append(n)
                    q_ndcgs[q_id] = n
                    s = compute_deterministic_spearman(dq, 'pred_score', ascending=False)
                    if s is not None: spearmans.append(s)
                    regrets.append(compute_top1_regret(dq, 'pred_score', ascending=False))

                res = {
                    'fold': fold_idx + 1,
                    'held_out_unit': held_out_unit,
                    'val_queries': n_val_queries,
                    'val_rows': n_val_rows,
                    'ndcg3': float(np.mean(ndcgs)),
                    'spearman': float(np.mean(spearmans)) if spearmans else None,
                    'regret': float(np.mean(regrets)),
                    'rmse': rmse,
                    'query_ndcgs': q_ndcgs
                }
                fold_results[m_id].append(res)

            elif m_family == 'xgboost_stage2':
                feat_cols = m['features']
                X_tr = df_tr[feat_cols].astype(np.float32)
                y_tr = df_tr['target'].astype(np.float64)
                X_va = df_va[feat_cols].astype(np.float32)

                model = xgb.XGBRegressor(
                    max_depth=2,
                    min_child_weight=2,
                    learning_rate=0.1,
                    n_estimators=200,
                    subsample=1.0,
                    colsample_bytree=0.6,
                    reg_lambda=1.0,
                    random_state=42
                )
                model.fit(X_tr, y_tr)
                preds = model.predict(X_va)

                df_va_eval = df_va.copy()
                df_va_eval['pred_score'] = preds
                rmse = float(np.sqrt(mean_squared_error(df_va_eval['target'], preds)))

                ndcgs, spearmans, regrets = [], [], []
                q_ndcgs = {}
                for q_id in val_queries:
                    dq = df_va_eval[df_va_eval['query_id'] == q_id]
                    n = compute_ndcg3(dq, 'pred_score', ascending=False)
                    ndcgs.append(n)
                    q_ndcgs[q_id] = n
                    s = compute_deterministic_spearman(dq, 'pred_score', ascending=False)
                    if s is not None: spearmans.append(s)
                    regrets.append(compute_top1_regret(dq, 'pred_score', ascending=False))

                res = {
                    'fold': fold_idx + 1,
                    'held_out_unit': held_out_unit,
                    'val_queries': n_val_queries,
                    'val_rows': n_val_rows,
                    'ndcg3': float(np.mean(ndcgs)),
                    'spearman': float(np.mean(spearmans)) if spearmans else None,
                    'regret': float(np.mean(regrets)),
                    'rmse': rmse,
                    'query_ndcgs': q_ndcgs
                }
                fold_results[m_id].append(res)

            elif m_family == 'xgboost_stage1':
                feat_cols = m['features']
                X_tr = df_tr[feat_cols].astype(np.float32)
                y_tr = df_tr['target'].astype(np.float64)
                X_va = df_va[feat_cols].astype(np.float32)

                model = xgb.XGBRegressor(
                    max_depth=3,
                    learning_rate=0.1,
                    n_estimators=100,
                    random_state=42
                )
                model.fit(X_tr, y_tr)
                preds = model.predict(X_va)

                df_va_eval = df_va.copy()
                df_va_eval['pred_score'] = preds
                rmse = float(np.sqrt(mean_squared_error(df_va_eval['target'], preds)))

                ndcgs, spearmans, regrets = [], [], []
                q_ndcgs = {}
                for q_id in val_queries:
                    dq = df_va_eval[df_va_eval['query_id'] == q_id]
                    n = compute_ndcg3(dq, 'pred_score', ascending=False)
                    ndcgs.append(n)
                    q_ndcgs[q_id] = n
                    s = compute_deterministic_spearman(dq, 'pred_score', ascending=False)
                    if s is not None: spearmans.append(s)
                    regrets.append(compute_top1_regret(dq, 'pred_score', ascending=False))

                res = {
                    'fold': fold_idx + 1,
                    'held_out_unit': held_out_unit,
                    'val_queries': n_val_queries,
                    'val_rows': n_val_rows,
                    'ndcg3': float(np.mean(ndcgs)),
                    'spearman': float(np.mean(spearmans)) if spearmans else None,
                    'regret': float(np.mean(regrets)),
                    'rmse': rmse,
                    'query_ndcgs': q_ndcgs
                }
                fold_results[m_id].append(res)

            elif m_family == 'xgboost_demeaned':
                feat_cols = m['features']
                X_tr = df_tr[feat_cols].astype(np.float32)
                # Target is demeaned strictly by training query means!
                y_tr = y_tr_demeaned.astype(np.float64)
                X_va = df_va[feat_cols].astype(np.float32)

                model = xgb.XGBRegressor(
                    max_depth=2,
                    min_child_weight=2,
                    learning_rate=0.1,
                    n_estimators=200,
                    subsample=1.0,
                    colsample_bytree=0.6,
                    reg_lambda=1.0,
                    random_state=42
                )
                model.fit(X_tr, y_tr)
                # Predictions are predicted within-query deviation
                preds_demeaned = model.predict(X_va)

                df_va_eval = df_va.copy()
                df_va_eval['pred_score'] = preds_demeaned
                # For raw RMSE, add global train mean (pure training statistic, NO validation labels used)
                preds_raw = preds_demeaned + global_train_target_mean
                rmse = float(np.sqrt(mean_squared_error(df_va_eval['target'], preds_raw)))

                ndcgs, spearmans, regrets = [], [], []
                q_ndcgs = {}
                for q_id in val_queries:
                    dq = df_va_eval[df_va_eval['query_id'] == q_id]
                    # Ranking by pred_score DESC is mathematically identical with or without query mean!
                    n = compute_ndcg3(dq, 'pred_score', ascending=False)
                    ndcgs.append(n)
                    q_ndcgs[q_id] = n
                    s = compute_deterministic_spearman(dq, 'pred_score', ascending=False)
                    if s is not None: spearmans.append(s)
                    regrets.append(compute_top1_regret(dq, 'pred_score', ascending=False))

                res = {
                    'fold': fold_idx + 1,
                    'held_out_unit': held_out_unit,
                    'val_queries': n_val_queries,
                    'val_rows': n_val_rows,
                    'ndcg3': float(np.mean(ndcgs)),
                    'spearman': float(np.mean(spearmans)) if spearmans else None,
                    'regret': float(np.mean(regrets)),
                    'rmse': rmse,
                    'query_ndcgs': q_ndcgs
                }
                fold_results[m_id].append(res)

        print(f"  Fold {fold_idx+1:2d}/16 ({held_out_unit:<12}): {n_val_queries:2d} queries, {n_val_rows:2d} rows evaluated.")

    # ─────────────────────────────────────────────────────────────
    # SUMMARY AGGREGATION & PAIRED COMPARISONS
    # ─────────────────────────────────────────────────────────────
    ref_id = 'xgb_stage2_74'
    ref_folds = fold_results[ref_id]
    ref_unit_ndcgs = {f['held_out_unit']: f['ndcg3'] for f in ref_folds}

    summary = {}
    for m in models_to_run:
        m_id = m['id']
        folds = fold_results[m_id]

        unit_ndcgs = [f['ndcg3'] for f in folds]
        unit_spearmans = [f['spearman'] for f in folds if f['spearman'] is not None]
        unit_regrets = [f['regret'] for f in folds]
        unit_rmses = [f['rmse'] for f in folds if f['rmse'] is not None]

        # Query-level pooling across all 78 dev queries
        all_q_ndcgs = []
        for f in folds:
            all_q_ndcgs.extend(list(f['query_ndcgs'].values()))

        # Paired comparisons against reference (xgb_stage2_74)
        paired_diffs = []
        units_improved = 0
        units_tied = 0
        units_degraded = 0

        for f in folds:
            u = f['held_out_unit']
            diff = f['ndcg3'] - ref_unit_ndcgs[u]
            paired_diffs.append(diff)
            if diff > 1e-6:
                units_improved += 1
            elif diff < -1e-6:
                units_degraded += 1
            else:
                units_tied += 1

        best_unit_idx = int(np.argmax(unit_ndcgs))
        worst_unit_idx = int(np.argmin(unit_ndcgs))

        mean_ndcg = float(np.mean(unit_ndcgs))
        std_ndcg = float(np.std(unit_ndcgs))
        query_mean_ndcg = float(np.mean(all_q_ndcgs))

        summary[m_id] = {
            'name': m['name'],
            'family': m.get('family'),
            'features': m.get('feat'),
            '16fold_unit_mean_ndcg3': mean_ndcg,
            '16fold_unit_std_ndcg3': std_ndcg,
            'query_macro_mean_ndcg3': query_mean_ndcg,
            '16fold_unit_mean_spearman': float(np.mean(unit_spearmans)) if unit_spearmans else None,
            '16fold_unit_mean_regret': float(np.mean(unit_regrets)),
            '16fold_unit_mean_rmse': float(np.mean(unit_rmses)) if unit_rmses else None,
            'best_unit': {'unit': folds[best_unit_idx]['held_out_unit'], 'ndcg3': folds[best_unit_idx]['ndcg3']},
            'worst_unit': {'unit': folds[worst_unit_idx]['held_out_unit'], 'ndcg3': folds[worst_unit_idx]['ndcg3']},
            'paired_diff_vs_ref_mean': float(np.mean(paired_diffs)),
            'units_improved_vs_ref': units_improved,
            'units_tied_vs_ref': units_tied,
            'units_degraded_vs_ref': units_degraded,
            'satisfies_challenger_rule': bool((mean_ndcg - summary.get(ref_id, {}).get('16fold_unit_mean_ndcg3', mean_ndcg) >= 0.02) and (units_improved >= 10))
        }

    # Print summary table
    print("\n" + "=" * 95)
    print(f"{'Model':<35} {'Unit NDCG@3':<14} {'Qry NDCG@3':<14} {'Regret':<10} {'Spearman':<10} {'Diff vs Ref':<12} {'Impr/16'}")
    print("-" * 95)
    for m_id, s in summary.items():
        diff_str = f"{s['paired_diff_vs_ref_mean']:+.4f}" if m_id != ref_id else "REFERENCE"
        impr_str = f"{s['units_improved_vs_ref']}/16" if m_id != ref_id else "-"
        rmse_str = f"{s['16fold_unit_mean_rmse']:.4f}" if s['16fold_unit_mean_rmse'] else "N/A"
        spm_str = f"{s['16fold_unit_mean_spearman']:.4f}" if s['16fold_unit_mean_spearman'] else "N/A"
        print(f"{s['name']:<35} {s['16fold_unit_mean_ndcg3']:<14.4f} {s['query_macro_mean_ndcg3']:<14.4f} {s['16fold_unit_mean_regret']:<10.4f} {spm_str:<10} {diff_str:<12} {impr_str}")
    print("=" * 95)

    # ─────────────────────────────────────────────────────────────
    # DECISION RULE EVALUATION
    # ─────────────────────────────────────────────────────────────
    ref_ndcg = summary[ref_id]['16fold_unit_mean_ndcg3']
    challengers = []
    for m_id, s in summary.items():
        if m_id in [ref_id, 'hypopg', 'random']:
            continue
        ndcg_gain = s['16fold_unit_mean_ndcg3'] - ref_ndcg
        improved_units = s['units_improved_vs_ref']
        if ndcg_gain >= 0.02 and improved_units >= 10:
            challengers.append((m_id, s))

    if challengers:
        decision_verdict = f"Challenger(s) detected: {[c[0] for c in challengers]}"
    else:
        decision_verdict = "Stage-2 XGBoost remains the development-set reference."

    print(f"\nDECISION RULE RESULT: {decision_verdict}")

    # ─────────────────────────────────────────────────────────────
    # SAVE EXPERIMENT JSON ARTIFACT
    # ─────────────────────────────────────────────────────────────
    out_json = {
        'metadata': {
            'timestamp': datetime.now().isoformat(),
            'experiment': 'Controlled Model Comparison',
            'cv_method': 'Leave-One-Structural-Unit-Out Cross-Validation (16 folds)',
            'dev_rows': 371,
            'dev_structural_units': 16,
            'dev_queries': int(df_train['query_id'].nunique()),
            'holdout_touched': False,
            'holdout_rows': 228
        },
        'feature_sets': {
            'set_A_count': len(FEATURES_74),
            'set_B_count': len(FEATURES_49),
            'constant_features_removed': CONSTANT_FEATURES
        },
        'decision_rule': {
            'condition_1': 'Mean Macro NDCG@3 improvement >= +0.02 vs Stage-2 XGBoost',
            'condition_2': 'Improves NDCG on at least 10 of the 16 held-out structural units',
            'verdict': decision_verdict
        },
        'summary': summary,
        'fold_results': fold_results,
        'structural_units': train_units
    }

    results_path = 'experiments/controlled_model_comparison_results.json'
    with open(results_path, 'w') as f:
        json.dump(out_json, f, indent=2)
    print(f"\nSaved structured results to: {results_path}")

    return out_json

if __name__ == '__main__':
    run_experiment()
