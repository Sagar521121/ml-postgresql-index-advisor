import pandas as pd

from src.index_advisor.candidate_generator import generate_candidates
from src.index_advisor.hypopg_evaluator import evaluate_candidate


def collect_experiments(benchmark_queries):
    """
    Run benchmark queries through candidate generation
    and HypoPG evaluation.

    Returns a list of experiment records.
    """

    records = []

    for query_name, query in benchmark_queries.items():

        candidates = generate_candidates(query)

        for candidate in candidates:

            result = evaluate_candidate(
                query,
                candidate
            )

            record = {
                "query_name": query_name,
                "query": query.strip(),

                "candidate_table": candidate["table"],
                "candidate_columns": ",".join(
                    candidate["columns"]
                ),
                "index_type": candidate["index_type"],

                "baseline_cost": result["baseline_cost"],
                "hypothetical_cost": result["hypothetical_cost"],
                "cost_reduction": result["cost_reduction"],
                "cost_reduction_percentage": (
                    result["cost_reduction_percentage"]
                ),

                "baseline_node_type": None,
                "hypothetical_node_type": (
                    result["root_node_type"]
                ),

                "plan_rows": result["plan_rows"],
            }

            records.append(record)

    return records


def save_experiment_records(records, output_path):
    """
    Save experiment records to a CSV file.
    """

    dataframe = pd.DataFrame(records)

    dataframe.to_csv(
        output_path,
        index=False
    )

    return dataframe
