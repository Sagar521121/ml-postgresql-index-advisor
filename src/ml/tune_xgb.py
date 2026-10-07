import json
import os
import sys
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import GroupKFold, ParameterSampler
from sklearn.metrics import mean_squared_error
from datetime import datetime

# Adjust Python path so we can import from data_loader
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from data_loader import load_and_preprocess_data, split_data

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
    'plan_changed', 'scan_structure_changed', 'join_structure_changed', 'candidate_used_in_hypo_plan', 'candidate_unused_in_hypo_plan'
]

def calculate_ndcg(df_query: pd.DataFrame) -> float:
    df = df_query.copy()
    df['relevance'] = np.maximum(0, df['target'])
    
    df_pred = df.sort_values(by=['predicted_target', 'candidate_id'], ascending=[False, True]).head(3)
    dcg = sum(rel / np.log2(idx + 2) for idx, rel in enumerate(df_pred['relevance']))
    
    df_ideal = df.sort_values(by=['relevance', 'candidate_id'], ascending=[False, True]).head(3)
    idcg = sum(rel / np.log2(idx + 2) for idx, rel in enumerate(df_ideal['relevance']))
    
    if idcg == 0:
        return 1.0
    return dcg / idcg

def tune_model():
    print("Loading data...")
    json_path = 'experiments/final_benchmark_results.json'
    csv_path = 'experiments/job_similarity_components.csv'
    
    rows, mapping = load_and_preprocess_data(json_path, csv_path)
    train_rows, test_rows = split_data(rows, test_size=0.2, random_state=42)
    
    # Assertions on split
    assert len(train_rows) == 371, f"Expected 371 train rows, got {len(train_rows)}"
    assert len(test_rows) == 228, f"Expected 228 test rows, got {len(test_rows)}"
    
    train_units = set(r['structural_unit_id'] for r in train_rows)
    test_units = set(r['structural_unit_id'] for r in test_rows)
    assert not train_units.intersection(test_units), "Test structural units leaked into training!"
    assert len(train_units) == 16, f"Expected exactly 16 structural units in train, got {len(train_units)}"
    
    # Assertions on data
    assert len(FEATURES) == 74, f"Expected 74 features, got {len(FEATURES)}"
    
    # Build dataframe for train rows
    df_train_full = pd.DataFrame(train_rows)
    
    if 'target' not in df_train_full.columns:
        df_train_full['target'] = np.log((df_train_full['baseline_runtime_ms'] + 1) / (df_train_full['actual_indexed_runtime_ms'] + 1))
    
    # Convert booleans to float32
    for col in ['plan_changed', 'scan_structure_changed', 'join_structure_changed', 'candidate_used_in_hypo_plan', 'candidate_unused_in_hypo_plan']:
        df_train_full[col] = df_train_full[col].astype(np.float32)
        
    X_train_full = df_train_full[FEATURES].astype(np.float32)
    y_train_full = df_train_full['target'].astype(np.float32)
    groups = df_train_full['structural_unit_id'].values
    
    # Integrity checks
    assert X_train_full.shape[1] == 74, "X does not have 74 columns"
    assert X_train_full.select_dtypes(include=[np.number]).shape[1] == 74, "Not all X columns are numeric"
    assert np.all(np.isfinite(X_train_full.values)), "X contains non-finite values"
    assert np.all(np.isfinite(y_train_full.values)), "y contains non-finite values"
    
    # No leakage checks
    leakage_cols = ['target', 'baseline_runtime_ms', 'actual_indexed_runtime_ms', 'query_id', 'candidate_id', 'family_id', 'structural_unit_id', 'candidate_table', 'candidate_columns', 'candidate_index_type', 'candidate_index_sql', 'baseline_plan_hash', 'hypo_plan_hash']
    for col in leakage_cols:
        assert col not in FEATURES, f"Leakage column {col} found in features!"
    
    # Ensure no controls or invalid rows
    assert not any(df_train_full.get('is_control', [False]*len(df_train_full))), "Controls found in training data"
    assert not any(~df_train_full.get('status', ['SUCCESS']*len(df_train_full)).isin(['SUCCESS', 'TIMEOUT'])), "Invalid status rows found"
    
    print("Integrity checks passed. Defining search space...")
    
    param_grid = {
        'max_depth': [2, 3, 4],
        'min_child_weight': [2, 5, 10],
        'learning_rate': [0.01, 0.05, 0.1],
        'n_estimators': [100, 200, 300],
        'subsample': [0.6, 0.8, 1.0],
        'colsample_bytree': [0.4, 0.6, 0.8],
        'reg_lambda': [1.0, 5.0, 10.0]
    }
    
    n_iter = 30
    random_state = 42
    sampler = ParameterSampler(param_grid, n_iter=n_iter, random_state=random_state)
    configs = list(sampler)
    
    gkf = GroupKFold(n_splits=4)
    
    all_results = []
    
    best_rmse = float('inf')
    best_config = None
    best_ndcg = None
    best_rmse_std = None
    best_ndcg_std = None
    
    print(f"Starting {n_iter} iterations of hyperparameter tuning...")
    
    for i, config in enumerate(configs):
        rmse_scores = []
        ndcg_scores = []
        
        for train_idx, val_idx in gkf.split(X_train_full, y_train_full, groups=groups):
            X_tr, y_tr = X_train_full.iloc[train_idx], y_train_full.iloc[train_idx]
            X_va, y_va = X_train_full.iloc[val_idx], y_train_full.iloc[val_idx]
            
            # Verify no intersection
            tr_groups = set(groups[train_idx])
            va_groups = set(groups[val_idx])
            assert not tr_groups.intersection(va_groups), "Group intersection in CV fold!"
            
            # Train model
            model = xgb.XGBRegressor(
                **config,
                random_state=42
            )
            model.fit(X_tr, y_tr)
            
            # Predict
            preds = model.predict(X_va)
            rmse = np.sqrt(mean_squared_error(y_va, preds))
            
            # NDCG@3 calculation
            df_val = df_train_full.iloc[val_idx].copy()
            df_val['predicted_target'] = preds
            
            query_ndcgs = []
            for q_id in df_val['query_id'].unique():
                df_q = df_val[df_val['query_id'] == q_id]
                query_ndcgs.append(calculate_ndcg(df_q))
                
            macro_ndcg = np.mean(query_ndcgs)
            
            rmse_scores.append(rmse)
            ndcg_scores.append(macro_ndcg)
            
        mean_rmse = np.mean(rmse_scores)
        std_rmse = np.std(rmse_scores)
        mean_ndcg = np.mean(ndcg_scores)
        std_ndcg = np.std(ndcg_scores)
        
        config_result = {
            'iteration': i + 1,
            'params': config,
            'mean_rmse': float(mean_rmse),
            'std_rmse': float(std_rmse),
            'mean_ndcg_3': float(mean_ndcg),
            'std_ndcg_3': float(std_ndcg),
            'fold_rmse_scores': [float(x) for x in rmse_scores],
            'fold_ndcg_scores': [float(x) for x in ndcg_scores]
        }
        all_results.append(config_result)
        
        print(f"Iter {i+1:2d} | RMSE: {mean_rmse:.4f} (±{std_rmse:.4f}) | NDCG@3: {mean_ndcg:.4f} (±{std_ndcg:.4f}) | Params: {config}")
        
        if mean_rmse < best_rmse:
            best_rmse = mean_rmse
            best_config = config
            best_ndcg = mean_ndcg
            best_rmse_std = std_rmse
            best_ndcg_std = std_ndcg

    all_results_sorted = sorted(all_results, key=lambda x: x['mean_rmse'])
    
    # Baseline comparison
    baseline_rmse = 0.4631
    baseline_ndcg = 0.7851
    
    rmse_improvement_abs = baseline_rmse - best_rmse
    rmse_improvement_rel = (baseline_rmse - best_rmse) / baseline_rmse
    
    ndcg_improvement_abs = best_ndcg - baseline_ndcg
    ndcg_improvement_rel = (best_ndcg - baseline_ndcg) / baseline_ndcg
    
    improved = bool(best_rmse < baseline_rmse)
    
    results_to_save = {
        'search_configuration': {
            'search_space': param_grid,
            'n_iter': n_iter,
            'random_state': random_state,
        },
        'cv_configuration': {
            'method': 'GroupKFold',
            'n_splits': 4,
            'group_column': 'structural_unit_id'
        },
        'primary_scoring_metric': 'RMSE',
        'best_result': {
            'hyperparameters': best_config,
            'mean_cv_rmse': float(best_rmse),
            'rmse_std': float(best_rmse_std),
            'macro_ndcg_3': float(best_ndcg),
            'ndcg_std': float(best_ndcg_std)
        },
        'baseline_comparison': {
            'baseline_rmse': baseline_rmse,
            'baseline_ndcg_3': baseline_ndcg,
            'absolute_rmse_improvement': float(rmse_improvement_abs),
            'relative_rmse_improvement': float(rmse_improvement_rel),
            'absolute_ndcg_improvement': float(ndcg_improvement_abs),
            'relative_ndcg_improvement': float(ndcg_improvement_rel),
            'tuning_improved_baseline': improved
        },
        'all_configurations': all_results_sorted,
        'integrity_checks': {
            'train_rows': len(train_rows),
            'train_structural_units': len(train_units),
            'test_rows_untouched': len(test_rows),
            'features_used': len(FEATURES),
            'finite_features': True,
            'finite_target': True,
            'leakage_checked': True,
            'controls_excluded': True
        }
    }
    
    os.makedirs('experiments', exist_ok=True)
    with open('experiments/xgb_tuning_results.json', 'w') as f:
        json.dump(results_to_save, f, indent=2)
        
    print("\n=== TUNING SUMMARY ===")
    print(f"Best Configuration: {best_config}")
    print(f"Best RMSE: {best_rmse:.4f} (Baseline: {baseline_rmse})")
    print(f"Best NDCG: {best_ndcg:.4f} (Baseline: {baseline_ndcg})")
    print(f"Improved? {'Yes' if improved else 'No'}")
    print("Results saved to experiments/xgb_tuning_results.json")

if __name__ == '__main__':
    tune_model()
