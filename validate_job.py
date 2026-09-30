import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

JOB_DIR = Path("benchmarks/job")

conn = psycopg.connect(
    host=os.getenv("DB_HOST", "localhost"),
    port=os.getenv("DB_PORT", "5432"),
    dbname="job_imdb",
    user=os.getenv("DB_USER", "postgres"),
    password=os.getenv("DB_PASSWORD"),
)

results = []

with conn:
    with conn.cursor() as cur:
        for path in sorted(JOB_DIR.glob("*.sql")):
            if path.name in {"fkindexes.sql", "schema.sql"}:
                continue

            query = path.read_text(encoding="utf-8").strip()

            try:
                cur.execute(f"EXPLAIN (FORMAT JSON) {query}")
                plan = cur.fetchone()[0]

                root = plan[0]["Plan"]

                results.append({
                    "query": path.name,
                    "status": "OK",
                    "cost": root.get("Total Cost"),
                    "plan_rows": root.get("Plan Rows"),
                    "root_node": root.get("Node Type"),
                })

            except Exception as e:
                conn.rollback()

                results.append({
                    "query": path.name,
                    "status": "FAILED",
                    "cost": None,
                    "plan_rows": None,
                    "root_node": str(e).splitlines()[0],
                })

for result in results:
    print(result)

print(f"\nTotal queries: {len(results)}")
print(f"Successful: {sum(r['status'] == 'OK' for r in results)}")
print(f"Failed: {sum(r['status'] == 'FAILED' for r in results)}")
