import pandas as pd


DATASET_PATH = "experiments/benchmark_results.csv"


def main():

    df = pd.read_csv(DATASET_PATH)

    print("=" * 70)
    print("DATASET INSPECTION")
    print("=" * 70)

    print(f"\nTotal experiment records: {len(df)}")

    print(
        f"Unique queries: "
        f"{df['query_name'].nunique()}"
    )

    print(
        f"Unique candidate indexes: "
        f"{df[['candidate_table', 'candidate_columns']].drop_duplicates().shape[0]}"
    )

    print(
        f"Unique cost reduction values: "
        f"{df['cost_reduction_percentage'].nunique()}"
    )

    print("\n" + "-" * 70)
    print("Candidate Indexes")
    print("-" * 70)

    candidates = (
        df[
            [
                "candidate_table",
                "candidate_columns"
            ]
        ]
        .drop_duplicates()
    )

    print(candidates.to_string(index=False))

    print("\n" + "-" * 70)
    print("Cost Reduction Statistics")
    print("-" * 70)

    print(
        df["cost_reduction_percentage"].describe()
    )

    print("\n" + "-" * 70)
    print("Unique Cost Reduction Values")
    print("-" * 70)

    print(
        df["cost_reduction_percentage"]
        .value_counts()
        .sort_index()
        .to_string()
    )

    print("\n" + "-" * 70)
    print("Experiment Records by Candidate")
    print("-" * 70)

    grouped = (
        df.groupby(
            [
                "candidate_table",
                "candidate_columns"
            ]
        )
        .agg(
            experiments=("query_name", "count"),
            min_benefit=(
                "cost_reduction_percentage",
                "min"
            ),
            max_benefit=(
                "cost_reduction_percentage",
                "max"
            ),
            avg_benefit=(
                "cost_reduction_percentage",
                "mean"
            )
        )
        .reset_index()
    )

    print(
        grouped.to_string(index=False)
    )


if __name__ == "__main__":
    main()
