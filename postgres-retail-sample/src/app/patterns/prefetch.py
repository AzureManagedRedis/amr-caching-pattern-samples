"""Reference-data prefetching - categories and brands.

Maps to the "Reference-data prefetching" row in the article. Stable data that is
read constantly and changes rarely is loaded into Redis up front (at startup)
and served directly, instead of waiting for a cache miss. Call
`prefetch_reference_data` again to refresh after the source changes.
"""
import json

from ..cache import cache
from ..db import fetch_all

CATEGORIES_KEY = "ref:categories"
BRANDS_KEY = "ref:brands"


async def prefetch_reference_data() -> None:
    r = cache()
    categories = await fetch_all("SELECT id, name FROM categories ORDER BY name")
    brands = await fetch_all("SELECT id, name FROM brands ORDER BY name")
    await r.set(CATEGORIES_KEY, json.dumps(categories))
    await r.set(BRANDS_KEY, json.dumps(brands))


async def get_categories() -> list[dict]:
    value = await cache().get(CATEGORIES_KEY)
    return json.loads(value) if value else []


async def get_brands() -> list[dict]:
    value = await cache().get(BRANDS_KEY)
    return json.loads(value) if value else []
