import os
import json
import glob
from src.dataset.runner import run_benchmark_collection
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

def main():
    # 1. Load queries
    query_files = glob.glob('benchmarks/job/*.sql')
    queries = {}
    for f in query_files:
        name = os.path.basename(f).replace('.sql', '')
        with open(f, 'r') as file:
            queries[name] = file.read()

    print(f"Loaded {len(queries)} queries.")

    # 2. Run Pilot
    builder = run_benchmark_collection(queries, pilot=True, pilot_max_pairs=20)

    # 3. Dump results for reporting
    results = {
        "summary": builder.summary(),
        "rows": [r.as_flat_dict() for r in builder.rows],
        "rejected": builder.rejected
    }

    with open('pilot_results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Saved pilot_results.json")

if __name__ == '__main__':
    main()
