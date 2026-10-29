"""Simulates other writers for the event-driven refresh demo (step 6).

These functions write Azure Cosmos DB directly and deliberately don't touch
Redis, the way an import, admin tool, or another service would. The Azure
Functions trigger for Azure Cosmos DB in functions/function_app.py reads the
change feed on `products` and, within seconds:

- `restock`: refreshes the cached product with `SET ... XX KEEPTTL`, so a hot
  product stays cached with the new stock.
- `soft_delete`: deletes the cached product. The latest version change feed
  doesn't include deletes, so the article removes a product by setting
  `isDeleted` and a `ttl`; Azure Cosmos DB removes the item when the TTL expires.

Both also delete the category listing, which the next read rebuilds.
"""
from ..config import settings
from ..db import products


def restock(category_id: str, product_id: str, quantity: int):
    products.patch_item(
        item=product_id,
        partition_key=category_id,
        patch_operations=[{"op": "incr", "path": "/stock", "value": quantity}],
    )


def soft_delete(category_id: str, product_id: str):
    products.patch_item(
        item=product_id,
        partition_key=category_id,
        patch_operations=[
            {"op": "set", "path": "/isDeleted", "value": True},
            {"op": "set", "path": "/ttl", "value": settings.soft_delete_ttl_seconds},
        ],
    )
