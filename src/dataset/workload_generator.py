def generate_workload():
    """
    Generate a controlled collection of SQL queries
    for the ML index-advisor experiments.
    """

    queries = {}

    query_id = 1

    # --------------------------------------------------
    # Orders: customer_id
    # --------------------------------------------------

    for customer_id in [
        1,
        100,
        500,
        1000,
        2500,
        5000,
        7500,
        9000,
        9999,
    ]:

        queries[f"Q{query_id}_customer_{customer_id}"] = f"""
            SELECT *
            FROM orders
            WHERE customer_id = {customer_id};
        """

        query_id += 1

    # --------------------------------------------------
    # Orders: amount
    # --------------------------------------------------

    for amount in [
        100,
        1000,
        3000,
        5000,
        7000,
        8000,
        9000,
        9500,
        9900,
    ]:

        queries[f"Q{query_id}_amount_{amount}"] = f"""
            SELECT *
            FROM orders
            WHERE amount > {amount};
        """

        query_id += 1

    # --------------------------------------------------
    # Orders: status
    # --------------------------------------------------

    for status in [
        "completed",
        "pending",
        "cancelled",
    ]:

        queries[f"Q{query_id}_status_{status}"] = f"""
            SELECT *
            FROM orders
            WHERE status = '{status}';
        """

        query_id += 1

    # --------------------------------------------------
    # Orders: order_date
    # --------------------------------------------------

    dates = [
        "2025-01-01",
        "2025-02-15",
        "2025-04-01",
        "2025-06-15",
        "2025-08-20",
        "2025-10-10",
        "2025-12-31",
    ]

    for date in dates:

        queries[f"Q{query_id}_date_{date}"] = f"""
            SELECT *
            FROM orders
            WHERE order_date = DATE '{date}';
        """

        query_id += 1

    # --------------------------------------------------
    # Customers: city
    # --------------------------------------------------

    for city in [
        "Delhi",
        "Mumbai",
        "Bangalore",
        "Pune",
    ]:

        queries[f"Q{query_id}_city_{city}"] = f"""
            SELECT *
            FROM customers
            WHERE city = '{city}';
        """

        query_id += 1

    # --------------------------------------------------
    # Customers: age
    # --------------------------------------------------

    for age in [
        20,
        25,
        30,
        35,
        40,
        45,
        50,
        60,
    ]:

        queries[f"Q{query_id}_age_{age}"] = f"""
            SELECT *
            FROM customers
            WHERE age > {age};
        """

        query_id += 1

    # --------------------------------------------------
    # JOIN workloads
    # --------------------------------------------------

    for city in [
        "Delhi",
        "Mumbai",
        "Bangalore",
        "Pune",
    ]:

        queries[f"Q{query_id}_join_city_{city}"] = f"""
            SELECT
                c.customer_id,
                c.city,
                o.amount
            FROM customers c
            JOIN orders o
                ON c.customer_id = o.customer_id
            WHERE c.city = '{city}';
        """

        query_id += 1

    return queries
