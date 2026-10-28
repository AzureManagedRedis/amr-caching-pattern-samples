"""Write-through: update Azure SQL, then update the cached product.

Matches step 5 of the article. The OUTPUT clause returns the committed price in
the same statement, and the cache is updated only after commit() succeeds.
"""
import json

from ..cache import cache
from ..db import get_db


def update_price(product_id: int, new_price: float):
    with get_db() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE dbo.Products
            SET Price = ?
            OUTPUT inserted.ProductId, inserted.Price
            WHERE ProductId = ?;
            """,
            (new_price, product_id),
        )
        row = cursor.fetchone()
        conn.commit()

    if row is None:
        return

    key = f"product:{product_id}"
    cached = cache.get(key)
    product = json.loads(cached) if cached is not None else None
    if product is None:
        cache.delete(key)  # Nothing to update; the next read loads the row.
        return
    product["price"] = float(row.Price)
    cache.set(key, json.dumps(product), keepttl=True)
