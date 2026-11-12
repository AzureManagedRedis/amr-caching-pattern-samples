"""Write-through: patch the price in Azure Cosmos DB, then update the cache.

Matches step 4 of "Improve efficiency of reads by using a cache with Azure Cosmos DB".
A partial document update (patch) returns the full updated item, so the
app caches it without a second read and deletes the category listing, which
still shows the old price. Passing the item's `_etag` makes the write fail if
someone else changed the item first (optimistic concurrency).

`rename_category_on_products` keeps the category name that each product stores
in step with a category rename.
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
    pipe = cache.pipeline(transaction=False)
    pipe.set(f"product:{category_id}:{product_id}", json.dumps(clean(updated)),
             ex=PRODUCT_TTL + random.randint(0, 60))
    pipe.delete(f"category:{category_id}:top")
    pipe.execute()


def rename_category_on_products(category_id: str, name: str):
    """Products store the category name, so a rename also updates them.

    Every product in a category shares one partition, so a single-partition
    query finds them all. Each patch returns the updated product, which is
    cached the same way as in `update_price`. The category listing doesn't
    show the category name, so it stays cached.
    """
    ids = list(products.query_items("SELECT VALUE c.id FROM c", partition_key=category_id))
    pipe = cache.pipeline(transaction=False)
    for product_id in ids:
        updated = products.patch_item(
            item=product_id,
            partition_key=category_id,
            patch_operations=[{"op": "set", "path": "/categoryName", "value": name}],
        )
        pipe.set(f"product:{category_id}:{product_id}", json.dumps(clean(updated)),
                 ex=PRODUCT_TTL + random.randint(0, 60))
    pipe.execute()
