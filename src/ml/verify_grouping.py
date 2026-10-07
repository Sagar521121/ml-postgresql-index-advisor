import sys
import os
from collections import Counter
from data_loader import load_and_preprocess_data, split_data, load_canonical_structural_mapping

def main():
    # Assume script is run from project root
    json_path = 'experiments/final_benchmark_results.json'
    csv_path = 'experiments/job_similarity_components.csv'
    
    try:
        mapping = load_canonical_structural_mapping(csv_path)
        rows, _ = load_and_preprocess_data(json_path, csv_path)
        
        # Mapping verification
        structural_units = set(mapping.values())
        print(f"Total canonical structural units defined: {len(structural_units)}")
        
        assigned_units = set(r['structural_unit_id'] for r in rows)
        print(f"Total structural units present in data: {len(assigned_units)}")
        
        if len(structural_units) != 20:
            print(f"FAIL: Expected exactly 20 canonical structural units, got {len(structural_units)}")
            sys.exit(1)
            
        if len(assigned_units) != 20:
            print(f"FAIL: Expected all 20 structural units to be present in data, got {len(assigned_units)}")
            sys.exit(1)
            
        if len(rows) != 599:
            print(f"FAIL: Expected exactly 599 rows, got {len(rows)}")
            sys.exit(1)
            
        null_mappings = [r for r in rows if r['structural_unit_id'] is None or r['structural_unit_id'] == '']
        if null_mappings:
            print("FAIL: Found rows with null/unknown structural mappings.")
            sys.exit(1)
            
        train_rows, test_rows = split_data(rows, test_size=0.2, random_state=42)
        
        train_units = set(r['structural_unit_id'] for r in train_rows)
        test_units = set(r['structural_unit_id'] for r in test_rows)
        
        intersection = train_units.intersection(test_units)
        if intersection:
            print(f"FAIL: Structural units leak between train and test: {intersection}")
            sys.exit(1)
            
        # Verify multi-family blocks are indivisible
        # A multi-family block is indivisible if all queries with the same structural unit
        # end up in the same split (train or test), which is guaranteed by GroupShuffleSplit, 
        # but let's explicitly verify it.
        # Check that no C70_* unit appears in both
        for unit in assigned_units:
            if unit.startswith('C70_'):
                if unit in train_units and unit in test_units:
                    print(f"FAIL: Multi-family block {unit} was divided across train and test!")
                    sys.exit(1)
        
        print("\nPASS: All verification checks passed.")
        
        print("\n--- Structural Unit Assignment ---")
        for k, v in sorted(mapping.items(), key=lambda x: int(x[0])):
            print(f"Family {k} -> {v}")
            
        print("\n--- Split Statistics ---")
        print(f"Train rows: {len(train_rows)}")
        print(f"Test rows: {len(test_rows)}")
        print(f"Train structural units: {len(train_units)}")
        print(f"Test structural units: {len(test_units)}")
        
        print("\nTrain units:", sorted(list(train_units)))
        print("Test units:", sorted(list(test_units)))
        
    except Exception as e:
        print(f"FAIL: Exception occurred: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
