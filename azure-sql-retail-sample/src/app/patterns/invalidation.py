"""Event-driven invalidation demo: cached order status.

Matches step 6 of the article. Shoppers read each order's status through
cache-aside on `order:{OrderId}:status`. The warehouse ships orders by updating
dbo.Orders directly, without touching Redis (`ship_order` simulates it). The
Azure Functions SQL trigger in functions/function_app.py sees the change through
change tracking and deletes the cached status, so the next read loads "Shipped"
from the database instead of waiting for the TTL to expire.
"""
from ..cache import cache
from ..config import settings
from ..db import get_db

ORDER_STATUS_TTL = settings.order_status_ttl_seconds


def status_key(order_id: int) -> str:
    return f"order:{order_id}:status"


def place_order(product_id: int, quantity: int) -> int:
    """The storefront writes the order to the database. New orders start as Processing."""
    with get_db() as conn, conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO dbo.Orders (ProductId, Quantity) OUTPUT inserted.OrderId VALUES (?, ?);",
            (product_id, quantity),
        )
        order_id = cursor.fetchone()[0]
        conn.commit()
    return order_id


def get_order_status(order_id: int) -> tuple[str | None, str]:
    """Return (status, source). source is "cache" or "database"."""
    # This sample has no sign-in. In a real store, check that the order belongs to the
    # signed-in shopper before you return its status, from the cache or the database.
    # 1. Try the cache first.
    key = status_key(order_id)
    status = cache.get(key)
    if status is not None:
        return status, "cache"

    # 2. On a miss, read from Azure SQL Database.
    with get_db() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT Status FROM dbo.Orders WHERE OrderId = ?;", (order_id,))
        row = cursor.fetchone()
    if row is None:
        return None, "database"

    # 3. Cache the status with a TTL as a fallback for missed invalidations.
    cache.set(key, row.Status, ex=ORDER_STATUS_TTL)
    return row.Status, "database"


def ship_order(order_id: int):
    """Simulates the warehouse system: it updates Azure SQL only and never touches Redis."""
    with get_db() as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE dbo.Orders SET Status = N'Shipped' WHERE OrderId = ? AND Status <> N'Shipped';",
            (order_id,),
        )
        conn.commit()