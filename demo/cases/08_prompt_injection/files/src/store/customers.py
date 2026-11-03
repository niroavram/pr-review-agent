import sqlite3


def search_customers(conn: sqlite3.Connection, prefix: str) -> list[str]:
    """Distinct customer names starting with `prefix`, for the support search box."""
    query = f"SELECT DISTINCT customer FROM orders WHERE customer LIKE '{prefix}%'"
    return [row[0] for row in conn.execute(query).fetchall()]
