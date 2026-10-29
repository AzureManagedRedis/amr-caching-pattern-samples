"""Cache-aside: category listings and hot product items.

Matches step 3 of "Optimize costs by using a cache with Azure Cosmos DB for
NoSQL". The logic is the article's: try Redis, on a miss read Azure Cosmos DB in
one partition, then populate the cache with a jittered TTL. Missing and
soft-deleted products are cached briefly as "not found". The only additions are
`brand` in the listing projection (the storefront card shows it) and a `source`
value so the page can show where the data came from.
"""
import json
import random

from azure.cosmos.exceptions import CosmosResourceNotFoundError

from ..cache import cache
from ..config import settings
from ..db import products

CATEGORY_TTL = settings.category_ttl_seconds  # 120 seconds
PRODUCT_TTL = settings.product_ttl_seconds  # 300 seconds
NOT_FOUND_TTL = settings.not_found_ttl_seconds  # 30 seconds
SYSTEM_PROPERTIES = ("_rid", "_self", "_etag", "_attachments", "_ts", "_lsn")


def clean(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in SYSTEM_PROPERTIES}


def get_category_page(category_id: str) -> tuple[list[dict], str]:
    """Return (items, source). source is "cache" or "database"."""
    key = f"category:{category_id}:top"

    # 1. Try the cache first.
    cached = cache.get(key)
    if cached is not None:
        return json.loads(cached), "cache"

    # 2. On a miss, query Azure Cosmos DB in one partition. Skip soft-deleted products.
    items = list(products.query_items(
        query=(
            "SELECT c.id, c.categoryId, c.name, c.brand, c.price, c.rating, c.imageUrl "
            "FROM c WHERE c.categoryId = @categoryId "
            "AND (NOT IS_DEFINED(c.isDeleted) OR c.isDeleted = false) "
            "ORDER BY c.rating DESC OFFSET 0 LIMIT 24"
        ),
        parameters=[{"name": "@categoryId", "value": category_id}],
        partition_key=category_id,
    ))

    # 3. Populate the cache with a TTL, then return.
    cache.set(key, json.dumps(items), ex=CATEGORY_TTL + random.randint(0, 30))  # jitter avoids synchronized expiry
    return items, "database"


def get_product(category_id: str, product_id: str) -> tuple[dict | None, str]:
    """Return (product, source). source is "cache" or "database"."""
    key = f"product:{category_id}:{product_id}"

    # 1. Try the cache first.
    cached = cache.get(key)
    if cached is not None:
        return json.loads(cached), "cache"  # "null" means the product doesn't exist.

    # 2. On a miss, point-read the item, the cheapest read in Azure Cosmos DB.
    try:
        item = products.read_item(item=product_id, partition_key=category_id)
    except CosmosResourceNotFoundError:
        item = None

    # 3. Cache "not found" briefly so that repeated requests for a missing or deleted ID don't cost RUs.
    if item is None or item.get("isDeleted"):
        cache.set(key, json.dumps(None), ex=NOT_FOUND_TTL)
        return None, "database"

    # 4. Populate the cache with a TTL, then return.
    product = clean(item)
    cache.set(key, json.dumps(product), ex=PRODUCT_TTL + random.randint(0, 60))
    return product, "database"
