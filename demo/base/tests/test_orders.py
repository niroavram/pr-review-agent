from src.store import orders
from src.store.db import connect


def test_create_and_get_order() -> None:
    conn = connect()
    oid = orders.create_order(conn, "alice", 1250)
    assert orders.get_order(conn, oid) == (oid, "alice", 1250)
