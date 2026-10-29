"""Reference-data prefetching kept current with SQL change tracking.

Matches step 4 of the article. `load_categories` runs at startup; the background
job in jobs.py runs `sync_categories` on a schedule so it reads only the rows
that changed since the last sync.
"""
from ..cache import cache
from ..db import get_db

CATEGORIES_KEY = "ref:categories"
SYNC_KEY = "sync:categories:version"


def load_categories():
    with get_db() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT CHANGE_TRACKING_CURRENT_VERSION();")
        version = cursor.fetchone()[0]
        cursor.execute("SELECT CategoryId, Name FROM dbo.Categories;")
        rows = cursor.fetchall()

    pipe = cache.pipeline()
    pipe.delete(CATEGORIES_KEY)
    if rows:
        pipe.hset(CATEGORIES_KEY, mapping={str(r.CategoryId): r.Name for r in rows})
    pipe.set(SYNC_KEY, version)
    pipe.execute()


def sync_categories():
    last = cache.get(SYNC_KEY)
    with get_db() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT CHANGE_TRACKING_CURRENT_VERSION(), "
                       "CHANGE_TRACKING_MIN_VALID_VERSION(OBJECT_ID('dbo.Categories'));")
        current, min_valid = cursor.fetchone()
        if last is None or int(last) < min_valid:
            load_categories()
            return
        cursor.execute(
            "SELECT ct.CategoryId, ct.SYS_CHANGE_OPERATION AS Op, c.Name "
            "FROM CHANGETABLE(CHANGES dbo.Categories, ?) AS ct "
            "LEFT JOIN dbo.Categories AS c ON c.CategoryId = ct.CategoryId;",
            (int(last),),
        )
        changes = cursor.fetchall()

    pipe = cache.pipeline()
    for ch in changes:
        if ch.Op == "D":
            pipe.hdel(CATEGORIES_KEY, str(ch.CategoryId))
        else:
            pipe.hset(CATEGORIES_KEY, str(ch.CategoryId), ch.Name)
    pipe.set(SYNC_KEY, current)
    pipe.execute()
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
