# Event-driven cache refresh with the Azure Functions trigger for Azure Cosmos DB.
#
# The trigger reads the change feed and calls these functions with every changed
# item, no matter who changed it: the storefront, an import, or someone in Data
# Explorer. Each function keeps a different part of the cache current:
#
# - refresh_products (step 6): refreshes cached products, deletes soft-deleted
#   ones, and deletes the affected category listings.
# - update_bestsellers (step 7): maintains the best-sellers sorted set.
# - refresh_reference (step 4): keeps the prefetched reference-data hashes current.
#
# All three share the `leases` container, which the Bicep template creates: with
# only a data-plane role, the trigger can't create it. Each function uses its own
# lease prefix so their checkpoints stay separate.
#
# Each function imports `shared.cache` inside its body, not at the top of this file.
# The Python worker loads this file while its event loop is running, and the
# redis-entraid credential provider blocks that loop while it requests the first
# token, so the function host never starts. A synchronous function runs on a
# separate thread, where the first token request completes normally.
import json                                   # To serialize the changed items

import azure.functions as func                # The Azure Functions Python library

app = func.FunctionApp()                      # Registers the functions in this file


# Step 6: run this function whenever items in the products container are created or updated.
@app.cosmos_db_trigger(
    arg_name="changes",                       # The parameter that receives the changed items
    database_name="retail",
    container_name="products",                # The container to watch
    connection="CosmosDBConnection",          # App setting prefix for the account connection
    lease_container_name="leases",            # Checkpoints, so the function resumes after a restart
    create_lease_container_if_not_exists=False,
)
def refresh_products(changes: func.DocumentList) -> None:
    from shared.cache import cache, clean  # cache from step 2, clean() from step 3
    # 1. Refresh each changed product that's already cached, or delete it if it was soft-deleted.
    pipe = cache.pipeline()
    categories = set()
    for doc in changes:
        item = clean(dict(doc))
        key = f"product:{item['categoryId']}:{item['id']}"
        if item.get("isDeleted"):
            pipe.delete(key)
        else:
            pipe.set(key, json.dumps(item), xx=True, keepttl=True)  # refresh only if cached
        categories.add(item["categoryId"])
    # 2. Delete the listing for each affected category. The next read rebuilds it.
    for category_id in categories:
        pipe.delete(f"category:{category_id}:top")
    pipe.execute()
    print(f"[products] refreshed {len(changes)} item(s) in {sorted(categories)}", flush=True)


# Step 7: run this function whenever items in the orders container are created or updated.
@app.cosmos_db_trigger(
    arg_name="orders",
    database_name="retail",
    container_name="orders",
    connection="CosmosDBConnection",
    lease_container_name="leases",
    lease_container_prefix="bestsellers-",    # Keeps these checkpoints separate from step 6
    create_lease_container_if_not_exists=False,
)
def update_bestsellers(orders: func.DocumentList) -> None:
    from shared.cache import cache
    for doc in orders:
        order = dict(doc)
        # 1. Skip canceled orders.
        if order.get("status") == "cancelled":
            continue
        # 2. Count each order once: the first time any version of it appears in the feed.
        if not cache.set(f"order:{order['id']}:counted", 1, nx=True, ex=7 * 24 * 3600):
            continue
        # 3. Add each line's quantity to the product's score.
        pipe = cache.pipeline()
        for line in order["lines"]:
            pipe.zincrby("bestsellers", line["quantity"], f"{line['categoryId']}:{line['productId']}")
        pipe.execute()
        print(f"[orders] counted order {order['id']}", flush=True)


# Step 4: keep the prefetched reference data current from the change feed on the
# reference container. For each changed item, write the same id, name, and data
# properties that load_reference stores, with HSET ref:{type} {id}.
@app.cosmos_db_trigger(
    arg_name="items",
    database_name="retail",
    container_name="reference",
    connection="CosmosDBConnection",
    lease_container_name="leases",
    lease_container_prefix="reference-",      # Keeps these checkpoints separate from steps 6 and 7
    create_lease_container_if_not_exists=False,
)
def refresh_reference(items: func.DocumentList) -> None:
    from shared.cache import cache
    pipe = cache.pipeline()
    for doc in items:
        item = dict(doc)
        value = {"id": item["id"], "name": item["name"], "data": item.get("data")}
        pipe.hset(f"ref:{item['type']}", item["id"], json.dumps(value))
    pipe.execute()
    print(f"[reference] refreshed {len(items)} item(s)", flush=True)
