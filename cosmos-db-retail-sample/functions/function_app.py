# Event-driven cache refresh with the Azure Functions trigger for Azure Cosmos DB.
#
# The trigger reads the change feed and calls these functions with every changed
# item, no matter who changed it: the storefront, the simulated warehouse, or
# someone in Data Explorer. Each function keeps a different part of the cache current:
#
# - refresh_order_status (step 6): writes each changed order's status to its
#   cached `order:<customerId>:<id>:status` key, if that key is cached.
# - update_bestsellers (step 7): maintains the best-sellers sorted set.
# - refresh_reference (step 4): keeps the prefetched reference-data hashes current.
#
# All three share the `leases` container, which the Bicep template creates: with
# only a data-plane role, the trigger can't create it. The two functions on the
# `orders` container use different lease prefixes so their checkpoints stay separate.
#
# Each function imports `shared.cache` inside its body, not at the top of this file.
# The Python worker loads this file while its event loop is running, and the
# redis-entraid credential provider blocks that loop while it requests the first
# token, so the function host never starts. A synchronous function runs on a
# separate thread, where the first token request completes normally.
import json

import azure.functions as func

app = func.FunctionApp()


# Step 6 (the article's code): invoked automatically when items in the orders container change
@app.cosmos_db_trigger(
    arg_name="orders",
    database_name="retail",
    container_name="orders",
    connection="CosmosDBConnection",
    lease_container_name="leases",
    create_lease_container_if_not_exists=False,
)
def refresh_order_status(orders: func.DocumentList) -> None:
    from shared.cache import cache     # Import here, not at the top, so the Functions host can start
    # Write each order's new status. xx=True skips orders that aren't cached,
    # and keepttl=True keeps the original expiry.
    pipe = cache.pipeline()
    for order in orders:
        pipe.set(f"order:{order['customerId']}:{order['id']}:status", order["status"], xx=True, keepttl=True)
    pipe.execute()
    print(f"[order-status] refreshed {len(orders)} order(s): "
          + ", ".join(f"{o['id']}={o['status']}" for o in orders), flush=True)


# Step 7: invoked automatically when items in the orders container change
@app.cosmos_db_trigger(
    arg_name="orders",
    database_name="retail",
    container_name="orders",
    connection="CosmosDBConnection",
    lease_container_name="leases",
    lease_container_prefix="bestsellers-",    # Keeps these checkpoints separate from refresh_order_status
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


# Step 4 (the article's code): invoked automatically when items in the reference container change
@app.cosmos_db_trigger(
    arg_name="items",
    database_name="retail",
    container_name="reference",
    connection="CosmosDBConnection",
    lease_container_name="leases",
    lease_container_prefix="reference-",      # Keeps these checkpoints separate from the orders functions
    create_lease_container_if_not_exists=False,
)
def refresh_reference(items: func.DocumentList) -> None:
    from shared.cache import cache
    # Write each changed item with the same properties that load_reference stores.
    pipe = cache.pipeline()
    for doc in items:
        item = dict(doc)
        value = {"id": item["id"], "name": item["name"], "data": item.get("data")}
        pipe.hset(f"ref:{item['type']}", item["id"], json.dumps(value))
    pipe.execute()
    print(f"[reference] refreshed {len(items)} item(s)", flush=True)
