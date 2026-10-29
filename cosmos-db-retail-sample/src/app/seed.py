"""Sample catalog and reference data.

`ensure_seeded` is idempotent and safe to call on every startup. It only upserts
items that don't exist yet, so it doesn't undo price changes, renames, or soft
deletes made while the app runs. It needs only the Cosmos DB Built-in Data
Contributor role: the database and containers come from the Bicep template,
because a data-plane role can't create them, and this script grants nothing.

It runs automatically on startup (AUTO_SEED=true). You can also run it manually:
    python -m app.seed
"""
from .db import products, reference
from .patterns.prefetch import load_all

# Catalog and product photos come from the MIT-licensed dotnet/eShop sample.
# Images are bundled under static/img (copied from the eShop repo).
PRODUCT_IMAGES = "/static/img"

# (id, name, sortOrder). The ID is the products partition key value (categoryId).
CATEGORIES = [
    ("footwear", "Footwear", 1),
    ("climbing", "Climbing", 2),
    ("ski-board", "Ski & Board", 3),
    ("bags", "Bags", 4),
    ("trekking", "Trekking", 5),
    ("jackets", "Jackets", 6),
    ("navigation", "Navigation", 7),
    ("cycling", "Cycling", 8),
]

# (name, description, price, categoryId, brand, rating, eShop image id). The product ID is the image ID.
PRODUCTS = [
    ("Wanderer Black Hiking Boots", "Waterproof leather hiking boots with a durable rubber sole.", 109.99, "footwear", "Daybird", 4.7, 1),
    ("Summit Pro Harness", "Lightweight climbing harness with adjustable leg loops and waist belt.", 89.99, "climbing", "Gravitator", 4.0, 2),
    ("Alpine Fusion Goggles", "Ski goggles with full UV protection and anti-fog lenses.", 79.99, "ski-board", "WildRunner", 4.2, 3),
    ("Expedition Backpack", "Spacious, durable nylon backpack for every outdoor adventure.", 129.99, "bags", "Quester", 4.0, 4),
    ("Blizzard Rider Snowboard", "Versatile all-level snowboard with a medium flex and twin shape.", 299.99, "ski-board", "B&R", 5.0, 5),
    ("Carbon Fiber Trekking Poles", "Lightweight carbon-fiber poles with adjustable cork grips.", 69.99, "trekking", "Raptor Elite", 4.3, 6),
    ("Frostbite Insulated Jacket", "Water-resistant insulated jacket for cold-weather adventures.", 179.99, "jackets", "Grolltex", 4.0, 8),
    ("VenturePro GPS Watch", "Rugged GPS watch with a built-in altimeter and compass.", 199.99, "navigation", "AirStrider", 4.5, 9),
    ("Trailblazer Bike Helmet", "Lightweight helmet with an adjustable fit system and ventilation.", 59.99, "cycling", "Green Equipment", 4.1, 10),
    ("Trailblaze Hiking Backpack", "40-liter ripstop backpack with an ergonomic, adjustable fit.", 89.99, "bags", "Daybird", 4.4, 13),
    ("Summit Pro Insulated Jacket", "Waterproof, breathable insulated jacket with recycled fill.", 249.99, "jackets", "Raptor Elite", 4.6, 15),
    ("EcoTrail Running Shoes", "Lightweight trail-running shoes made from recycled materials.", 119.99, "footwear", "Green Equipment", 5.0, 19),
]

# (id, name, data)
SHIPPING = [
    ("standard", "Standard (5 to 7 days)", {"price": 0.0, "sortOrder": 1}),
    ("express", "Express (1 to 2 days)", {"price": 14.99, "sortOrder": 2}),
]
CONFIG = [
    ("store", "Contoso Outdoors", {"currency": "USD", "freeShippingOver": 100}),
]

STOCK = 25


def _reference_items() -> list[dict]:
    items = [
        {"id": cid, "type": "category", "name": name, "data": {"sortOrder": order}}
        for cid, name, order in CATEGORIES
    ]
    items += [{"id": i, "type": "shipping", "name": n, "data": d} for i, n, d in SHIPPING]
    items += [{"id": i, "type": "config", "name": n, "data": d} for i, n, d in CONFIG]
    return items


def _product_items() -> list[dict]:
    return [
        {
            "id": str(eshop_id),
            "categoryId": category_id,
            "name": name,
            "brand": brand,
            "description": description,
            "price": price,
            "rating": rating,
            "stock": STOCK,
            "imageUrl": f"{PRODUCT_IMAGES}/{eshop_id}.webp",
        }
        for name, description, price, category_id, brand, rating, eshop_id in PRODUCTS
    ]


def _existing_ids(container) -> set[str]:
    return set(container.query_items("SELECT VALUE c.id FROM c", enable_cross_partition_query=True))


def ensure_seeded() -> None:
    created = 0
    for container, items in ((reference, _reference_items()), (products, _product_items())):
        existing = _existing_ids(container)
        for item in items:
            if item["id"] not in existing:
                container.upsert_item(item)
                created += 1
    if created:
        print(f"[seed] upserted {created} item(s).", flush=True)


if __name__ == "__main__":
    ensure_seeded()
    load_all()
    print("Seed complete.")
