"""Schema creation, SQL trigger permissions, and catalog seeding.

`ensure_seeded` is idempotent and safe to call on every startup. It holds a SQL
Server application lock so multiple app replicas don't seed at the same time,
then:

1. Runs schema.sql: tables, change tracking, and the az_func schema.
2. Creates a database user for the function app's managed identity and grants
   the permissions the Azure Functions SQL trigger needs (step 6 of the article).
3. Seeds the catalog if it's empty or out of date.

The app's managed identity is the server's Microsoft Entra admin, which lets it
do all of this. In production, run these scripts once from a deployment pipeline
and give the app only the grants in the article's "Prepare the database" section.

It runs automatically on startup (AUTO_SEED=true). You can also run it manually:
    python -m app.seed
"""
import re
import uuid
from pathlib import Path

from .config import settings
from .db import get_db
from .patterns.prefetch import load_categories

SCHEMA = Path(__file__).parent / "schema.sql"
SEED_LOCK = "retail-cache-sample-seed"

# Catalog and product photos come from the MIT-licensed dotnet/eShop sample.
# Images are bundled under static/img (copied from the eShop repo).
PRODUCT_IMAGES = "/static/img"

CATEGORIES = ["Footwear", "Climbing", "Ski & Board", "Bags", "Trekking", "Jackets", "Navigation", "Cycling"]

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

# (product index in PRODUCTS, rating)
REVIEWS = [(0, 5), (0, 4), (0, 5), (1, 4), (3, 5), (3, 3), (4, 5), (6, 4), (7, 5), (7, 4), (11, 5)]

STOCK = 25


def _batches(script: str) -> list[str]:
    """Split a T-SQL script on GO lines."""
    return [b.strip() for b in re.split(r"^\s*GO\s*$", script, flags=re.MULTILINE | re.IGNORECASE) if b.strip()]


def _grant_function_identity(cursor) -> None:
    """Grant the function app's identity what the SQL trigger needs (article step 6)."""
    name, client_id = settings.func_identity_name, settings.func_identity_client_id
    if not name or not client_id:
        print("[seed] FUNC_IDENTITY_NAME/CLIENT_ID not set; skipping SQL trigger grants.", flush=True)
        return
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", name):
        raise ValueError(f"Unexpected FUNC_IDENTITY_NAME: {name!r}")
    sid = "0x" + uuid.UUID(client_id).bytes_le.hex().upper()  # validates the GUID

    user = f"[{name}]"
    cursor.execute("SELECT 1 FROM sys.database_principals WHERE name = ?;", (name,))
    if cursor.fetchone() is None:
        # The app identity is the Entra admin here, and a managed identity admin can't
        # use FROM EXTERNAL PROVIDER unless the server identity can read Microsoft Entra ID.
        # Creating the user from the identity's client ID (SID, TYPE = E) skips that lookup.
        cursor.execute(f"CREATE USER {user} WITH SID = {sid}, TYPE = E;")
    cursor.execute(f"GRANT SELECT, VIEW CHANGE TRACKING ON OBJECT::dbo.Products TO {user};")
    cursor.execute(f"GRANT CREATE TABLE TO {user};")
    cursor.execute(f"GRANT ALTER, SELECT, INSERT, UPDATE, DELETE ON SCHEMA::az_func TO {user};")


def _grant_developer(cursor) -> None:
    """Give the deploying developer the app's least-privilege grants, for running locally."""
    if not settings.developer_object_id:
        return
    sid = "0x" + uuid.UUID(settings.developer_object_id).bytes_le.hex().upper()  # validates the GUID
    cursor.execute("SELECT 1 FROM sys.database_principals WHERE name = 'developer';")
    if cursor.fetchone() is None:
        # A Microsoft Entra user's SID is their object ID.
        cursor.execute(f"CREATE USER [developer] WITH SID = {sid}, TYPE = E;")
    cursor.execute("ALTER ROLE db_datareader ADD MEMBER [developer];")
    cursor.execute("ALTER ROLE db_datawriter ADD MEMBER [developer];")
    cursor.execute("GRANT VIEW CHANGE TRACKING ON SCHEMA::dbo TO [developer];")


def _seed_catalog(cursor) -> None:
    cursor.execute("SELECT Name FROM dbo.Products;")
    existing = {row.Name for row in cursor.fetchall()}
    if existing == {product[0] for product in PRODUCTS}:
        return  # catalog already current

    # Empty or changed catalog: reset the demo data and reseed.
    for table in ("ProductStats", "Reviews", "Products", "Categories"):
        cursor.execute(f"DELETE FROM dbo.{table};")

    categories = {}
    for name in CATEGORIES:
        cursor.execute("INSERT INTO dbo.Categories (Name) OUTPUT inserted.CategoryId VALUES (?);", (name,))
        categories[name] = cursor.fetchone()[0]

    product_ids = []
    for name, description, price, category, brand, eshop_id in PRODUCTS:
        cursor.execute(
            "INSERT INTO dbo.Products (CategoryId, Name, Brand, Description, ImageUrl, Price, Stock) "
            "OUTPUT inserted.ProductId VALUES (?, ?, ?, ?, ?, ?, ?);",
            (categories[category], name, brand, description, f"{PRODUCT_IMAGES}/{eshop_id}.webp", price, STOCK),
        )
        product_ids.append(cursor.fetchone()[0])

    for index, rating in REVIEWS:
        cursor.execute("INSERT INTO dbo.Reviews (ProductId, Rating) VALUES (?, ?);", (product_ids[index], rating))
    print(f"[seed] seeded {len(PRODUCTS)} products.", flush=True)


def ensure_seeded() -> None:
    # autocommit: ALTER DATABASE (in schema.sql) can't run inside a transaction.
    with get_db(autocommit=True) as conn, conn.cursor() as cursor:
        cursor.execute(
            "EXEC sp_getapplock @Resource = ?, @LockMode = 'Exclusive', @LockOwner = 'Session', @LockTimeout = 120000;",
            (SEED_LOCK,),
        )
        try:
            for batch in _batches(SCHEMA.read_text()):
                cursor.execute(batch)
            _grant_function_identity(cursor)
            _grant_developer(cursor)
            _seed_catalog(cursor)
        finally:
            cursor.execute("EXEC sp_releaseapplock @Resource = ?, @LockOwner = 'Session';", (SEED_LOCK,))


if __name__ == "__main__":
    ensure_seeded()
    load_categories()
    print("Seed complete.")
