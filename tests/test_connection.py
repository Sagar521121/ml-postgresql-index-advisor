from src.database.connection import get_connection


def main():
    try:
        conn = get_connection()

        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), version();")
            database, version = cur.fetchone()

        print("Connection successful!")
        print(f"Database: {database}")
        print(f"PostgreSQL: {version}")

        conn.close()

    except Exception as e:
        print("Connection failed!")
        print(e)


if __name__ == "__main__":
    main()