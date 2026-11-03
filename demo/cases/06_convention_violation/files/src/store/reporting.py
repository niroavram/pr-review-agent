import sqlite3


def revenue_dollars(conn: sqlite3.Connection) -> float:
    """Total revenue across all orders, in dollars."""
    (total_cents,) = conn.execute("SELECT COALESCE(SUM(total_cents), 0) FROM orders").fetchone()
    return total_cents / 100


def report_revenue(conn: sqlite3.Connection) -> None:
    """Show the revenue total to the operator."""
    print(f"Revenue: ${revenue_dollars(conn):.2f}")
