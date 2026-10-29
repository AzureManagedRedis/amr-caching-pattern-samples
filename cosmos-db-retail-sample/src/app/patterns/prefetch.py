"""Reference-data prefetch: categories, shipping options, and store settings.

Matches step 4 of "Optimize costs by using a cache with Azure Cosmos DB for
NoSQL". `load_reference` is the article's code: it loads every item of one type
from the `reference` container into the Redis hash `ref:{type}` with no TTL. The
app calls it for each type at startup. Reads use `HGETALL` and never cost RUs.

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


def load_all():
    for ref_type in REFERENCE_TYPES:
        load_reference(ref_type)


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
