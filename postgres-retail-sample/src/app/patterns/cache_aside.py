"""Cache-aside (lazy loading) - product catalog and detail reads.

Maps to the "Cache-aside" row in the article. The application checks Redis
first; on a miss it reads PostgreSQL, then populates the cache with a TTL. A few
popular products drive most reads, so the hit rate is high.
"""
import json

from ..cache import cache
from ..config import settings
from ..db import fetch_one

# Reused by the write-through pattern to refresh the same cached shape.
PRODUCT_SQL = (
    "SELECT p.id, p.name, p.description, p.price::float AS price, p.inventory, "
    "b.name AS brand, c.name AS category, p.image_url "
    "FROM products p "
    "JOIN brands b ON p.brand_id = b.id "
    "JOIN categories c ON p.category_id = c.id "
    "WHERE p.id = %s"
)


def key(product_id: int) -> str:
    return f"product:{product_id}"


async def get_product(product_id: int) -> tuple[dict | None, str]:
    """Return (product, source) where source is "cache" or "database"."""
    r = cache()

    # 1. Try the cache first.
    cached = await r.get(key(product_id))
    if cached is not None:
        return json.loads(cached), "cache"

    # 2. On a miss, read from PostgreSQL.
    product = await fetch_one(PRODUCT_SQL, (product_id,))
    if product is None:
        return None, "database"

    # 3. Populate the cache with a TTL, then return.
    await r.set(key(product_id), json.dumps(product), ex=settings.cache_ttl_seconds)
    return product, "database"
