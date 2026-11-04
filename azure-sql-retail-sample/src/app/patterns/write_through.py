"""Write-through: update Azure SQL, then update the cached product.

Matches step 5 of the article. The OUTPUT clause returns the committed price in
the same statement, and the cache is updated only after commit() succeeds.
"""
import json

from ..cache import cache
from ..db import get_db


def update_price(product_id: int, new_price: float):
    # 1. Save the new price. OUTPUT returns it in the same call, so there's no need to read it again.
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
        conn.commit()  # The database is updated first; the cache comes next.

    # 2. No row back means no product has this ID, so nothing changed. Stop.
    if row is None:
        return

    # 3. The product exists and its price changed. Check whether it's in the cache.
    key = f"product:{product_id}"
    cached = cache.get(key)
    product = json.loads(cached) if cached is not None else None

    # 4. Not cached, or cached as "not found" (now wrong): delete the key so the next read reloads it.
    if product is None:
        cache.delete(key)
        return

    # 5. Cached: update the price. keepttl=True keeps the original expiry. xx=True skips a
    #    key that expired or was deleted after the read, so it isn't recreated without an expiry.
    product["price"] = float(row.Price)
    cache.set(key, json.dumps(product), keepttl=True, xx=True)