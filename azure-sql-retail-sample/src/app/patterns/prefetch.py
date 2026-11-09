"""Reference-data prefetching kept current with SQL change tracking.

Matches step 4 of the article. `load_categories` runs at startup; the background
job in jobs.py runs `sync_categories` on a schedule so it reads only the rows
that changed since the last sync.
"""
from ..cache import cache
from ..db import get_db

CATEGORIES_KEY = "ref:categories"
SYNC_KEY = "sync:categories:version"  # the change tracking version the cache reflects


# Full load: at startup, or when the cache is too far behind to sync.
def load_categories():
    with get_db() as conn, conn.cursor() as cursor:
        # Read the version first so changes made during the load are caught by the next sync.
        cursor.execute("SELECT CHANGE_TRACKING_CURRENT_VERSION();")
        version = cursor.fetchone()[0]
        cursor.execute("SELECT CategoryId, Name FROM dbo.Categories;")
        rows = cursor.fetchall()
    # 1. Remove the saved version first. If this reload stops partway, the next sync reloads everything.
    cache.delete(SYNC_KEY)
    # 2. Replace the hash (CategoryId -> Name).
    pipe = cache.pipeline()
    pipe.delete(CATEGORIES_KEY)
    if rows:
        pipe.hset(CATEGORIES_KEY, mapping={str(r.CategoryId): r.Name for r in rows})
    pipe.execute()
    # 3. Save the version only after the hash is rebuilt.
    cache.set(SYNC_KEY, version)


# Incremental sync: run on a schedule.
def sync_categories():
    last = cache.get(SYNC_KEY)
    with get_db() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT CHANGE_TRACKING_CURRENT_VERSION(), "
                       "CHANGE_TRACKING_MIN_VALID_VERSION(OBJECT_ID('dbo.Categories'));")
        current, min_valid = cursor.fetchone()
        # Never loaded, or older than the retained change history: reload everything.
        if last is None or int(last) < min_valid:
            load_categories()
            return
        # Rows changed since the last sync. Name is NULL for deleted rows.
        cursor.execute(
            "SELECT ct.CategoryId, ct.SYS_CHANGE_OPERATION AS Op, c.Name "
            "FROM CHANGETABLE(CHANGES dbo.Categories, ?) AS ct "
            "LEFT JOIN dbo.Categories AS c ON c.CategoryId = ct.CategoryId;",
            (int(last),),
        )
        changes = cursor.fetchall()
        # Cleanup can remove change history mid-read. If the version is now too old, reload everything.
        cursor.execute("SELECT CHANGE_TRACKING_MIN_VALID_VERSION(OBJECT_ID('dbo.Categories'));")
        if int(last) < cursor.fetchone()[0]:
            load_categories()
            return
    # Apply the changes first.
    pipe = cache.pipeline()
    for ch in changes:  # Op is I (insert), U (update), or D (delete)
        if ch.Op == "D":
            pipe.hdel(CATEGORIES_KEY, str(ch.CategoryId))
        else:
            pipe.hset(CATEGORIES_KEY, str(ch.CategoryId), ch.Name)
    pipe.execute()
    # Save the version last. If the batch fails, the next run safely reapplies the same changes.
    cache.set(SYNC_KEY, current)
    if changes:
        print(f"[sync] applied {len(changes)} category change(s)", flush=True)


def get_categories() -> list[dict]:
    """Category chips for the storefront, served from the prefetched hash."""
    categories = cache.hgetall(CATEGORIES_KEY)
    return [{"id": int(cid), "name": name} for cid, name in sorted(categories.items(), key=lambda kv: int(kv[0]))]


def rename_category(category_id: int, name: str):
    """Admin edit that writes only to Azure SQL. sync_categories picks it up."""
    with get_db() as conn, conn.cursor() as cursor:
        cursor.execute("UPDATE dbo.Categories SET Name = ? WHERE CategoryId = ?;", (name, category_id))
        conn.commit()