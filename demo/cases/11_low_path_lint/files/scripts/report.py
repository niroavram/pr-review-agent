"""Print a tiny order report. Scripts may use print (CONV-002)."""

import sys

from src.store import orders
from src.store.db import connect


def main() -> None:
    conn = connect()
    orders.create_order(conn, "alice", 1250)
    orders.create_order(conn, "bob", 500)
    print(orders.get_order(conn, 1))
    print(orders.get_order(conn, 2))


if __name__ == "__main__":
    main()
