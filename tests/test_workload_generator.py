from src.dataset.workload_generator import generate_workload


def main():

    workload = generate_workload()

    print(f"Queries generated: {len(workload)}")

    print("\nFirst 10 queries")
    print("----------------")

    for i, (name, query) in enumerate(workload.items()):

        print(f"\n{name}")
        print(query.strip())

        if i == 9:
            break


if __name__ == "__main__":
    main()
