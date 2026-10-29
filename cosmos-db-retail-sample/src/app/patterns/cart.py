"""Cart and session offload: active carts live in Redis, orders in Azure Cosmos DB.

Matches step 8 of "Optimize costs by using a cache with Azure Cosmos DB for
NoSQL". Every "add to cart" click updates a Redis hash with a sliding TTL and
costs no RUs. Checkout reads current prices from Azure Cosmos DB, writes one
order whose ID is the checkout ID (an idempotency key), and deletes the cart. A
repeated submit of the same checkout returns the existing order instead of
creating a second one. The order has the shape the best-sellers function in
step 7 expects.
"""
from datetime import datetime, timezone

from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosResourceNotFoundError

from ..cache import cache
from ..config import settings
from ..db import orders, products

CART_TTL = settings.cart_ttl_seconds  # Expire after 30 minutes of inactivity.


def add_to_cart(user_id: str, category_id: str, product_id: str, quantity: int = 1):
    # Runs on every click. Updates Redis only.
    key = f"cart:{user_id}"
    pipe = cache.pipeline()
    pipe.hincrby(key, f"{category_id}:{product_id}", quantity)
    pipe.expire(key, CART_TTL)
    pipe.execute()


def get_cart(user_id: str) -> dict[str, int]:
    key = f"cart:{user_id}"
    items = cache.hgetall(key)
    if items:
        cache.expire(key, CART_TTL)  # Sliding expiration
    return {member: int(qty) for member, qty in items.items()}


def checkout(user_id: str, customer_id: str, checkout_id: str) -> dict:
    """checkout_id is an idempotency key that the client generates once per checkout attempt."""
    # 1. A retry of a checkout that already succeeded returns the existing order.
    try:
        return orders.read_item(item=checkout_id, partition_key=customer_id)
    except CosmosResourceNotFoundError:
        pass

    cart = get_cart(user_id)
    if not cart:
        raise ValueError("The cart is empty or has expired.")

    # 2. Build the order lines. Read the current price from Azure Cosmos DB, not the cache.
    lines = []
    for member, quantity in cart.items():
        category_id, product_id = member.split(":", 1)
        product = products.read_item(item=product_id, partition_key=category_id)
        if product.get("isDeleted"):
            raise ValueError(f"Product {product_id} is no longer available.")
        lines.append({
            "categoryId": category_id,
            "productId": product_id,
            "quantity": quantity,
            "price": product["price"],
        })

    # 3. Save the order. Its ID is the checkout ID, so a duplicate submit can't create a second order.
    order = {
        "id": checkout_id,
        "customerId": customer_id,
        "status": "placed",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "lines": lines,
    }
    try:
        orders.create_item(order)
    except CosmosResourceExistsError:
        # A concurrent submit of the same checkout created the order first.
        order = orders.read_item(item=checkout_id, partition_key=customer_id)

    # 4. The order is saved, so remove the cart from Redis.
    cache.delete(f"cart:{user_id}")
    return order
