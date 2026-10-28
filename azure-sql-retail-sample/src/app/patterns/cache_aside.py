"""Cache-aside: read product pages from Redis, fall back to Azure SQL on a miss.

Matches step 3 of "Improve performance by using a cache with Azure SQL
Database". The only additions are display columns for the storefront UI and a
`source` value so the page can show where the data came from.
"""
import json
import random

from ..cache import cache
from ..config import settings
from ..db import get_db

PRODUCT_TTL = settings.product_ttl_seconds
NOT_FOUND_TTL = settings.not_found_ttl_seconds

PRODUCT_PAGE_SQL = """
SELECT p.ProductId, p.Name, p.Brand, p.Description, p.ImageUrl, p.Price, p.Stock,
       c.Name AS Category,
       r.ReviewCount, r.AvgRating
FROM dbo.Products AS p
JOIN dbo.Categories AS c ON c.CategoryId = p.CategoryId
OUTER APPLY (
    SELECT COUNT(*) AS ReviewCount, CAST(AVG(Rating * 1.0) AS DECIMAL(3,2)) AS AvgRating
    FROM dbo.Reviews WHERE ProductId = p.ProductId
) AS r
WHERE p.ProductId = ?;
"""


def get_product(product_id: int) -> tuple[dict | None, str]:
    """Return (product, source). source is "cache" or "database"."""
    key = f"product:{product_id}"
    cached = cache.get(key)
    if cached is not None:
        return json.loads(cached), "cache"  # "null" means the product doesn't exist.

    with get_db() as conn, conn.cursor() as cursor:
        cursor.execute(PRODUCT_PAGE_SQL, (product_id,))
        row = cursor.fetchone()

    if row is None:
        # Negative caching: remember "not found" briefly so probes for missing
        # IDs don't run the join every time.
        cache.set(key, json.dumps(None), ex=NOT_FOUND_TTL)
        return None, "database"

    product = {
        "id": row.ProductId,
        "name": row.Name,
        "brand": row.Brand,
        "description": row.Description,
        "image_url": row.ImageUrl,
        "price": float(row.Price),
        "stock": row.Stock,
        "category": row.Category,
        "reviewCount": row.ReviewCount,
        "avgRating": float(row.AvgRating) if row.AvgRating is not None else None,
    }
    ttl = PRODUCT_TTL + random.randint(0, 60)  # jitter avoids synchronized expiry
    cache.set(key, json.dumps(product), ex=ttl)
    return product, "database"
