"""Event-driven refresh demo: cached order status.

Matches step 6 of "Optimize costs by using a cache with Azure Cosmos DB for
NoSQL". Shoppers read each order's status through cache-aside on
`order:<customerId>:<id>:status`. The warehouse ships orders by updating the `orders`
container directly, without touching Redis (`ship_order` simulates it). The
`refresh_order_status` function in functions/function_app.py reads the change
feed and writes the new status to the cached key, so the next read returns
"shipped" from the cache instead of waiting for the TTL to expire.
"""
from azure.cosmos.exceptions import CosmosAccessConditionFailedError, CosmosResourceNotFoundError

from ..cache import cache
from ..config import settings
from ..db import orders

# Long on purpose: without the change feed function, a shipped order would show "placed" this long.
ORDER_STATUS_TTL = settings.order_status_ttl_seconds


def status_key(customer_id: str, order_id: str) -> str:
    # Includes the partition key, so each customer reads only their own cached orders.
    return f"order:{customer_id}:{order_id}:status"


def get_order_status(customer_id: str, order_id: str) -> tuple[str | None, str]:
    """Return (status, source). source is "cache" or "database"."""
    # 1. Try the cache first.
    key = status_key(customer_id, order_id)
    status = cache.get(key)
    if status is not None:
        return status, "cache"

    # 2. On a miss, point-read the order from Azure Cosmos DB.
    try:
        order = orders.read_item(item=order_id, partition_key=customer_id)
    except CosmosResourceNotFoundError:
        return None, "database"

    # 3. Cache the status with a TTL as a fallback for missed updates.
    cache.set(key, order["status"], ex=ORDER_STATUS_TTL)
    return order["status"], "database"


def ship_order(customer_id: str, order_id: str):
    """Simulates the warehouse system: it updates Azure Cosmos DB only and never touches Redis."""
    try:
        orders.patch_item(
            item=order_id,
            partition_key=customer_id,
            patch_operations=[{"op": "set", "path": "/status", "value": "shipped"}],
            filter_predicate="FROM c WHERE c.status = 'placed'",  # only placed orders ship
        )
    except CosmosAccessConditionFailedError:
        pass  # Already shipped (or canceled): shipping again is a no-op.
