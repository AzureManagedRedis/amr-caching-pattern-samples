"""Best-sellers ranking from a Redis sorted set.

Matches step 6 of "Improve efficiency of reads by using a cache with Azure Cosmos DB".
The `update_bestsellers` function in functions/function_app.py reads the
change feed on `orders` and adds each order line's quantity with `ZINCRBY`, so
the app never runs a cross-partition aggregation over orders. The app reads the
top N in one call. Members are `{categoryId}:{productId}`, so the storefront can
fetch product details with `get_product` from step 3.
"""
from ..cache import cache


def get_bestsellers(n: int = 10) -> list[tuple[str, float]]:
    return cache.zrange("bestsellers", 0, n - 1, desc=True, withscores=True)
