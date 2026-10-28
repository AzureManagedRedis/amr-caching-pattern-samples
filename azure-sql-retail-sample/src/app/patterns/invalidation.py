"""Simulates an external writer for the event-driven invalidation demo.

`restock` updates Azure SQL directly and deliberately doesn't touch Redis, the
way a batch job, admin tool, or another service would. The Azure Functions SQL
trigger in functions/function_app.py (step 6 of the article) sees the change
through change tracking and deletes the product's cache key, so the next read
loads the new stock from the database.
"""
from ..db import get_db


def restock(product_id: int, quantity: int):
    with get_db() as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE dbo.Products SET Stock = Stock + ? WHERE ProductId = ?;",
            (quantity, product_id),
        )
        conn.commit()
