from src.store import orders
from src.store.db import connect


def test_find_orders_by_customer() -> None:
    conn = connect()
    orders.create_order(conn, "bob", 500)
    assert orders.find_orders_by_customer(conn, "bob") == [(1, 500)]
