"""Write-through - price and inventory updates.

Maps to the "Write-through" row in the article. The application updates
PostgreSQL and the cache in the same operation, so the storefront reflects a
price or inventory change immediately (read-after-write) instead of waiting for
a TTL to expire.
"""
import json

from ..cache import cache
from ..config import settings
from ..db import execute, fetch_one
from .cache_aside import PRODUCT_SQL, key


async def update_price(product_id: int, price: float) -> None:
    await execute("UPDATE products SET price = %s WHERE id = %s", (price, product_id))
    await _write_through(product_id)


async def _write_through(product_id: int) -> None:
    # DB (source of truth) is already written. Refresh the cache best-effort: on
    # failure, delete the key so the next read reloads from DB (there is no shared
    # transaction across DB and Redis).
    try:
        product = await fetch_one(PRODUCT_SQL, (product_id,))
        if product is not None:
            await cache().set(key(product_id), json.dumps(product), ex=settings.cache_ttl_seconds)
    except Exception as exc:  # noqa: BLE001 - cache is best-effort; never fail the write
        print(f"[write-through] cache update failed, invalidating {key(product_id)}: {exc}", flush=True)
        try:
            await cache().delete(key(product_id))
        except Exception:  # noqa: BLE001
            pass

