"""Print a tiny order report. Scripts may use print (CONV-002)."""

from src.store import orders
from src.store.db import connect


def main() -> None:
    conn = connect()
    orders.create_order(conn, "alice", 1250)
    print(orders.get_order(conn, 1))


if __name__ == "__main__":
    main()
