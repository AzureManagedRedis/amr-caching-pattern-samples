"""Event-driven pattern - order fulfillment with Redis Streams.

Maps to the "Event-driven invalidation" row in the article. Placing an order writes PostgreSQL (the
source of truth) and appends an event to a Redis Stream. A consumer-group worker
(see worker.py) advances the order through fulfillment states and updates a
cached order-status view. Customers read that fast projection; the cache is kept
fresh by events rather than by a TTL.
"""
from ..cache import cache
from ..config import settings
from ..db import fetch_one


def status_key(order_id: int) -> str:
    return f"order:{order_id}:status"


async def place_order(product_id: int, quantity: int) -> int:
    # Write the order to PostgreSQL (source of truth).
    row = await fetch_one(
        "INSERT INTO orders (product_id, quantity, status) "
        "VALUES (%s, %s, 'placed') RETURNING id",
        (product_id, quantity),
    )
    order_id = row["id"]

    # Seed the cached status (with TTL) and publish an event to the trimmed stream.
    await cache().set(status_key(order_id), "placed", ex=settings.order_status_ttl_seconds)
    await cache().xadd(
        settings.orders_stream,
        {"order_id": order_id, "event": "placed"},
        maxlen=settings.orders_stream_maxlen,
        approximate=True,
    )
    return order_id


async def get_order_status(order_id: int) -> str | None:
    # Read the live projection from Redis; fall back to PostgreSQL on a miss.
    value = await cache().get(status_key(order_id))
    if value is not None:
        return value

    row = await fetch_one("SELECT status FROM orders WHERE id = %s", (order_id,))
    if row is None:
        return None
    await cache().set(status_key(order_id), row["status"], ex=settings.order_status_ttl_seconds)
    return row["status"]
