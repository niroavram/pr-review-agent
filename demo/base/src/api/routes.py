"""HTTP layer. Handlers stay thin and delegate to src/store and src/payments (CONV-003)."""

from fastapi import APIRouter

from src.payments.charges import apply_discount
from src.store import orders
from src.store.db import connect

router = APIRouter(prefix="/v1")
conn = connect()


@router.get("/public/orders/{order_id}")
def read_order(order_id: int) -> dict[str, object]:
    row = orders.get_order(conn, order_id)
    if row is None:
        return {"error": "not found"}
    return {"id": row[0], "customer": row[1], "total_cents": row[2]}


@router.post("/payments/{order_id}/discount")
def discount_order(order_id: int, percent: int) -> dict[str, object]:
    row = orders.get_order(conn, order_id)
    if row is None:
        return {"error": "not found"}
    return {"id": row[0], "total_cents": apply_discount(row[2], percent)}


@router.get("/admin/orders/{order_id}")
def admin_read_order(order_id: int) -> dict[str, object]:
    return read_order(order_id)
