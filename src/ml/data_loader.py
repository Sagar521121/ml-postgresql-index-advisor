import json
import csv
import re
from typing import Dict, Tuple, List
import numpy as np
from sklearn.model_selection import GroupShuffleSplit

def load_canonical_structural_mapping(csv_path: str) -> Dict[str, str]:
    """
    Loads the authoritative structural unit mapping from job_similarity_components.csv.
    Uses the Component_S70 column.
    Multi-family blocks remain as named (e.g. C70_1).
    Singletons are suffixed with their family ID (e.g. Singleton_3).
    """
    mapping = {}
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            family_id = row['Family']
            comp_s70 = row['Component_S70']
            if comp_s70 == 'Singleton':
                mapping[family_id] = f"Singleton_{family_id}"
            else:
                mapping[family_id] = comp_s70
    return mapping

def load_and_preprocess_data(json_path: str, mapping_csv_path: str) -> Tuple[List[Dict], Dict[str, str]]:
    """
    Loads benchmark observations and applies the canonical structural unit mapping.
    Filters out A/A controls, placebo controls, INVALID_PHYSICAL, and BUILD_INFEASIBLE.
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    mapping = load_canonical_structural_mapping(mapping_csv_path)
    
    processed_rows = []
    
    for row in data['rows']:
        status = row.get('status')
        # We only expect SUCCESS or TIMEOUT in the final benchmark results
        if status not in ['SUCCESS', 'TIMEOUT']:
            continue
            
        if row.get('is_control'):
            continue
            
        q_id = row['query_id']
        # Extract base family ID from query_id (e.g. "17e" -> "17", "6f" -> "6")
        match = re.match(r"^(\d+)", q_id)
        if not match:
            raise ValueError(f"Could not extract numeric family ID from query_id: {q_id}")
        
        canonical_family_id = match.group(1)
        
        # Override the structural_unit_id with the authoritative mapping
        if canonical_family_id not in mapping:
            raise ValueError(f"Family ID {canonical_family_id} not found in authoritative mapping.")
        
        row['structural_unit_id'] = mapping[canonical_family_id]
        row['canonical_family_id'] = canonical_family_id
        
        processed_rows.append(row)
        
    return processed_rows, mapping

def split_data(rows: List[Dict], test_size: float = 0.2, random_state: int = 42):
    """
    Performs a train/test split ensuring that structural units are not split across sets.
    """
    groups = [row['structural_unit_id'] for row in rows]
    
    # We use GroupShuffleSplit to split by structural_unit_id
    gss = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=random_state)
    
    # Dummy X array since we only need the indices
    X = np.zeros(len(rows))
    
    train_idx, test_idx = next(gss.split(X, groups=groups))
    
    train_rows = [rows[i] for i in train_idx]
    test_rows = [rows[i] for i in test_idx]
    
    return train_rows, test_rows

