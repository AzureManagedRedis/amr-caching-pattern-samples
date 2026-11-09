"""Reference-data prefetch: categories, shipping options, and store settings.

Reference-data prefetching, from the caching patterns table in "Optimize costs
by using a cache with Azure Cosmos DB". The article has no code step for it;
this sample includes it as an extra. `load_reference` loads every item of one type
from the `reference` container into the Redis hash `ref:{type}` with no TTL. At
startup, `load_all` loads only the hashes that don't exist yet, from one replica at
a time. Reads use `HGETALL` and never cost RUs.

The hashes are kept current by the change feed: the `refresh_reference` function
in functions/function_app.py runs the Azure Functions trigger for Azure Cosmos DB
on the `reference` container and writes each changed item with
`HSET ref:{type} {id}`. `rename_category` simulates an admin edit that writes
Azure Cosmos DB only.
"""
import json

from ..cache import cache
from ..db import reference

REFERENCE_TYPES = ("category", "shipping", "config")
PREFETCH_LOCK = "lock:prefetch"


def load_reference(ref_type: str):
    # 1. Read every item of this type from one partition.
    items = reference.query_items(
        query="SELECT c.id, c.name, c.data FROM c WHERE c.type = @type",
        parameters=[{"name": "@type", "value": ref_type}],
        partition_key=ref_type,
    )
    mapping = {i["id"]: json.dumps(i) for i in items}

    # 2. Replace the hash (id -> item) in one batch.
    key = f"ref:{ref_type}"
    pipe = cache.pipeline()
    pipe.delete(key)
    if mapping:
        pipe.hset(key, mapping=mapping)
    pipe.execute()


def load_all(force: bool = False):
    """Load every reference type. At startup, only hashes that don't exist yet are loaded."""
    # A short lock keeps two app replicas from loading at the same time.
    if not cache.set(PREFETCH_LOCK, "1", nx=True, ex=60):
        print("[prefetch] another replica is loading; skipped", flush=True)
        return
    try:
        for ref_type in REFERENCE_TYPES:
            # After a restart, an existing hash is already current from the change feed,
            # and reloading it could overwrite a newer value with an older one.
            if force or not cache.exists(f"ref:{ref_type}"):
                load_reference(ref_type)
                print(f"[prefetch] loaded ref:{ref_type}", flush=True)
            else:
                print(f"[prefetch] ref:{ref_type} already cached; kept", flush=True)
    finally:
        cache.delete(PREFETCH_LOCK)


def get_reference(ref_type: str) -> list[dict]:
    """Items of one type, served from the prefetched hash and sorted for display."""
    items = [json.loads(v) for v in cache.hgetall(f"ref:{ref_type}").values()]
    return sorted(items, key=lambda i: ((i.get("data") or {}).get("sortOrder", 0), i["name"]))


def rename_category(category_id: str, name: str):
    """Admin edit that writes Azure Cosmos DB only. The change feed updates the hash."""
    reference.patch_item(
        item=category_id,
        partition_key="category",
        patch_operations=[{"op": "set", "path": "/name", "value": name}],
    )
