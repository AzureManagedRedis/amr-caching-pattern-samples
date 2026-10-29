"""Write-through: patch the price in Azure Cosmos DB, then update the cache.

Matches step 5 of "Optimize costs by using a cache with Azure Cosmos DB for
NoSQL". A partial document update (patch) returns the full updated item, so the
app caches it without a second read and deletes the category listing, which
still shows the old price. Passing the item's `_etag` makes the write fail if
someone else changed the item first (optimistic concurrency).
"""
import json
import random

from azure.core import MatchConditions

from ..cache import cache
from ..db import products
from .cache_aside import PRODUCT_TTL, clean


def update_price(category_id: str, product_id: str, new_price: float, etag: str | None = None):
    # 1. If the caller passes the item's _etag, fail the write when someone else changed it first.
    kwargs = {}
    if etag:
        kwargs = {"etag": etag, "match_condition": MatchConditions.IfNotModified}

    # 2. Save the new price in Azure Cosmos DB. Patch returns the full updated item.
    updated = products.patch_item(
        item=product_id,
        partition_key=category_id,
        patch_operations=[{"op": "set", "path": "/price", "value": new_price}],
        **kwargs,
    )

    # 3. The write succeeded. Cache the updated product, and delete the category
    #    listing, which still shows the old price.
    pipe = cache.pipeline()
    pipe.set(f"product:{category_id}:{product_id}", json.dumps(clean(updated)),
             ex=PRODUCT_TTL + random.randint(0, 60))
    pipe.delete(f"category:{category_id}:top")
    pipe.execute()
