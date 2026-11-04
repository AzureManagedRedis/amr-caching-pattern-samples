"""Write-behind: buffer page-view counts in Redis and flush them to Azure SQL.

Matches step 7 of the article. jobs.py runs `flush_views` on a schedule and
holds a Redis lock so only one app replica flushes at a time.
"""
import json

from ..cache import cache
from ..db import get_db

# Both names share the {views} hash tag, so Redis stores them in the same cluster slot.
PENDING = "{views}:pending"    # New views collect here
FLUSHING = "{views}:flushing"  # The batch being written to the database

# Add each product's count to its total. Insert a row the first time a product is
# viewed, and skip products that no longer exist.
UPSERT_VIEWS_SQL = """
MERGE dbo.ProductStats WITH (HOLDLOCK) AS t
USING (SELECT j.ProductId, j.Views
       FROM OPENJSON(?) WITH (ProductId INT, Views BIGINT) AS j
       JOIN dbo.Products AS p ON p.ProductId = j.ProductId) AS s
    ON t.ProductId = s.ProductId
WHEN MATCHED THEN UPDATE SET Views = t.Views + s.Views
WHEN NOT MATCHED THEN INSERT (ProductId, Views) VALUES (s.ProductId, s.Views);
"""


def record_view(product_id: int):
    # Runs on every page view. Adds 1 to the product's count in Redis only.
    cache.hincrby(PENDING, str(product_id), 1)


def flush_views():
    # Runs on a schedule.
    # 1. If the last flush failed, its batch is still in FLUSHING, so retry it.
    #    Otherwise, move the pending counts to FLUSHING. New views start a fresh PENDING.
    if not cache.exists(FLUSHING):
        if not cache.exists(PENDING):
            return  # No views since the last flush.
        cache.rename(PENDING, FLUSHING)

    # 2. Turn the batch into JSON: [{"ProductId": 3, "Views": 5}, ...]
    counts = cache.hgetall(FLUSHING)
    rows = json.dumps([{"ProductId": int(pid), "Views": int(n)} for pid, n in counts.items()])

    # 3. Add all the counts to the database in one statement.
    with get_db() as conn, conn.cursor() as cursor:
        cursor.execute(UPSERT_VIEWS_SQL, (rows,))
        conn.commit()
    print(f"[flush] wrote views for {len(counts)} product(s)", flush=True)

    # 4. The database has the counts now, so remove the batch from Redis.
    cache.delete(FLUSHING)


def pending_views() -> dict[int, int]:
    """Views counted in Redis that haven't been flushed yet."""
    counts = {}
    for key in (FLUSHING, PENDING):
        for pid, n in cache.hgetall(key).items():
            counts[int(pid)] = counts.get(int(pid), 0) + int(n)
    return counts


def flushed_views() -> dict[int, int]:
    """Views already written to dbo.ProductStats."""
    with get_db() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT ProductId, Views FROM dbo.ProductStats;")
        return {r.ProductId: int(r.Views) for r in cursor.fetchall()}