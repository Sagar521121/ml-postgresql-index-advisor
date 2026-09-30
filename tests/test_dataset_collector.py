from src.dataset.collector import (
    collect_experiments,
    save_experiment_records
)

from src.dataset.workload_generator import generate_workload


def main():

    print("Generating workload...\n")

    benchmark_queries = generate_workload()

    print(
        f"Queries generated: "
        f"{len(benchmark_queries)}"
    )

    print("\nCollecting experiment data...\n")

    records = collect_experiments(
        benchmark_queries
    )

    print(
        f"Experiments collected: "
        f"{len(records)}"
    )

    output_path = "experiments/benchmark_results.csv"

    dataframe = save_experiment_records(
        records,
        output_path
    )

    print(
        f"\nDataset saved to: "
        f"{output_path}"
    )

    print("\nExperiment Dataset")
    print("------------------")

    print(
        dataframe[
            [
                "query_name",
                "candidate_table",
                "candidate_columns",
                "baseline_cost",
                "hypothetical_cost",
                "cost_reduction_percentage"
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
