import json
import os
import sys
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import GroupKFold
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

def run_baseline():
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
    
    # Assertions on data
    assert len(FEATURES) == 74, f"Expected 74 features, got {len(FEATURES)}"
    
    # Build dataframe for train rows
    df_train_full = pd.DataFrame(train_rows)
    
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
    
    # Ensure no controls or invalid rows
    assert not any(df_train_full['is_control']), "Controls found in training data"
    # (Other invalid rows like A/A are already handled by loader, let's just make sure)
    
    print("Integrity checks passed. Starting CV...")
    
    gkf = GroupKFold(n_splits=4)
    
    fold_results = []
    rmse_scores = []
    ndcg_scores = []
    
    fold = 1
    for train_idx, val_idx in gkf.split(X_train_full, y_train_full, groups=groups):
        X_tr, y_tr = X_train_full.iloc[train_idx], y_train_full.iloc[train_idx]
        X_va, y_va = X_train_full.iloc[val_idx], y_train_full.iloc[val_idx]
        
        # Verify no intersection
        tr_groups = set(groups[train_idx])
        va_groups = set(groups[val_idx])
        assert not tr_groups.intersection(va_groups), "Group intersection in CV fold!"
        
        # Train model
        model = xgb.XGBRegressor(
            max_depth=3,
            learning_rate=0.1,
            n_estimators=100,
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
        
        fold_results.append({
            'fold': fold,
            'train_rows': len(train_idx),
            'val_rows': len(val_idx),
            'train_structural_units': sorted(list(tr_groups)),
            'val_structural_units': sorted(list(va_groups)),
            'val_queries_count': len(df_val['query_id'].unique()),
            'rmse': float(rmse),
            'macro_ndcg_3': float(macro_ndcg)
        })
        print(f"Fold {fold}: RMSE={rmse:.4f}, NDCG@3={macro_ndcg:.4f}")
        fold += 1
        
    overall_rmse = np.mean(rmse_scores)
    overall_ndcg = np.mean(ndcg_scores)
    
    results = {
        'timestamp': datetime.now().isoformat(),
        'model_parameters': {
            'max_depth': 3,
            'learning_rate': 0.1,
            'n_estimators': 100,
            'random_state': 42,
            'model_type': 'XGBRegressor'
        },
        'features': {
            'count': len(FEATURES),
            'names': FEATURES
        },
        'cv_configuration': {
            'method': 'GroupKFold',
            'n_splits': 4,
            'group_column': 'structural_unit_id',
            'total_train_rows_used': len(train_rows)
        },
        'integrity_checks': {
            'test_rows_excluded': True,
            'test_rows_count': len(test_rows),
            'controls_excluded': True,
            'finite_values_verified': True,
            'feature_whitelist_enforced': True
        },
        'fold_results': fold_results,
        'overall_metrics': {
            'mean_rmse': float(overall_rmse),
            'std_rmse': float(np.std(rmse_scores)),
            'mean_macro_ndcg_3': float(overall_ndcg),
            'std_macro_ndcg_3': float(np.std(ndcg_scores))
        }
    }
    
    os.makedirs('experiments', exist_ok=True)
    with open('experiments/baseline_xgb_results.json', 'w') as f:
        json.dump(results, f, indent=2)
        
    print(f"\nDone! Overall RMSE: {overall_rmse:.4f}, NDCG@3: {overall_ndcg:.4f}")
    
if __name__ == '__main__':
    run_baseline()
