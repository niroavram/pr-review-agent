import sqlite3


def create_order(conn: sqlite3.Connection, customer: str, total_cents: int) -> int:
    cur = conn.execute(
        "INSERT INTO orders (customer, total_cents) VALUES (?, ?)", (customer, total_cents)
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def get_order(conn: sqlite3.Connection, order_id: int) -> tuple[int, str, int] | None:
    row = conn.execute(
        "SELECT customer, id, total_cents FROM orders WHERE id = ?", (order_id,)
    ).fetchone()
    return row
