"""Schema creation and catalog seeding.

`ensure_seeded` is idempotent and safe to call on every startup: it creates the
schema if needed and seeds the catalog only when it's empty, guarded by a
PostgreSQL advisory lock so multiple app replicas don't seed concurrently.

It runs automatically on startup (AUTO_SEED=true). You can also run it manually:
    python -m app.seed
"""
import asyncio
from pathlib import Path

from . import azure_auth
from . import cache as cache_module
from . import db
from .db import pool
from .patterns.prefetch import prefetch_reference_data

SCHEMA = Path(__file__).parent / "schema.sql"
SEED_LOCK = 727274  # arbitrary advisory-lock key shared by all replicas

# Catalog and product photos come from the MIT-licensed dotnet/eShop sample.
# Images are bundled under static/img (copied from the eShop repo).
PRODUCT_IMAGES = "/static/img"

CATEGORIES = ["Footwear", "Climbing", "Ski & Board", "Bags", "Trekking", "Jackets", "Navigation", "Cycling"]
BRANDS = ["Daybird", "Gravitator", "WildRunner", "Quester", "B&R", "Raptor Elite", "Grolltex", "AirStrider", "Green Equipment"]

# (name, description, price, category, brand, eShop image id)
PRODUCTS = [
    ("Wanderer Black Hiking Boots", "Waterproof leather hiking boots with a durable rubber sole.", 109.99, "Footwear", "Daybird", 1),
    ("Summit Pro Harness", "Lightweight climbing harness with adjustable leg loops and waist belt.", 89.99, "Climbing", "Gravitator", 2),
    ("Alpine Fusion Goggles", "Ski goggles with full UV protection and anti-fog lenses.", 79.99, "Ski & Board", "WildRunner", 3),
    ("Expedition Backpack", "Spacious, durable nylon backpack for every outdoor adventure.", 129.99, "Bags", "Quester", 4),
    ("Blizzard Rider Snowboard", "Versatile all-level snowboard with a medium flex and twin shape.", 299.99, "Ski & Board", "B&R", 5),
    ("Carbon Fiber Trekking Poles", "Lightweight carbon-fiber poles with adjustable cork grips.", 69.99, "Trekking", "Raptor Elite", 6),
    ("Frostbite Insulated Jacket", "Water-resistant insulated jacket for cold-weather adventures.", 179.99, "Jackets", "Grolltex", 8),
    ("VenturePro GPS Watch", "Rugged GPS watch with a built-in altimeter and compass.", 199.99, "Navigation", "AirStrider", 9),
    ("Trailblazer Bike Helmet", "Lightweight helmet with an adjustable fit system and ventilation.", 59.99, "Cycling", "Green Equipment", 10),
    ("Trailblaze Hiking Backpack", "40-liter ripstop backpack with an ergonomic, adjustable fit.", 89.99, "Bags", "Daybird", 13),
    ("Summit Pro Insulated Jacket", "Waterproof, breathable insulated jacket with recycled fill.", 249.99, "Jackets", "Raptor Elite", 15),
    ("EcoTrail Running Shoes", "Lightweight trail-running shoes made from recycled materials.", 119.99, "Footwear", "Green Equipment", 19),
]


async def ensure_seeded() -> None:
    """Create the schema and seed the catalog. Re-seeds if the catalog changed."""
    async with pool().connection() as conn:
        # Serialize seeding across replicas so only one seeds.
        await conn.execute("SELECT pg_advisory_lock(%s)", (SEED_LOCK,))
        try:
            await conn.execute(SCHEMA.read_text())

            cur = await conn.execute("SELECT name FROM products")
            existing = {row[0] for row in await cur.fetchall()}
            if existing == {product[0] for product in PRODUCTS}:
                return  # catalog already current

            # Empty or changed catalog: reset the demo data and reseed.
            await conn.execute("DELETE FROM orders")
            await conn.execute("DELETE FROM products")
            await conn.execute("DELETE FROM categories")
            await conn.execute("DELETE FROM brands")

            for name in CATEGORIES:
                await conn.execute("INSERT INTO categories (name) VALUES (%s)", (name,))
            for name in BRANDS:
                await conn.execute("INSERT INTO brands (name) VALUES (%s)", (name,))

            cur = await conn.execute("SELECT id, name FROM categories")
            categories = {name: cid for cid, name in await cur.fetchall()}
            cur = await conn.execute("SELECT id, name FROM brands")
            brands = {name: bid for bid, name in await cur.fetchall()}

            for name, description, price, category, brand, eshop_id in PRODUCTS:
                await conn.execute(
                    "INSERT INTO products (name, description, price, category_id, brand_id, image_url) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        name,
                        description,
                        price,
                        categories[category],
                        brands[brand],
                        f"{PRODUCT_IMAGES}/{eshop_id}.webp",
                    ),
                )
            print(f"Seeded {len(PRODUCTS)} products.", flush=True)
        finally:
            await conn.execute("SELECT pg_advisory_unlock(%s)", (SEED_LOCK,))


async def _standalone() -> None:
    await db.open_pool()
    await cache_module.open_cache()
    try:
        await ensure_seeded()
        await prefetch_reference_data()
        print("Seed complete.")
    finally:
        await cache_module.close_cache()
        await db.close_pool()
        await azure_auth.close_credential()


if __name__ == "__main__":
    asyncio.run(_standalone())
