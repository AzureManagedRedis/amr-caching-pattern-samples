# Event-driven invalidation with the Azure SQL trigger for Azure Functions.
#
# The trigger uses change tracking to call this function with every changed row in
# dbo.Products, no matter who changed it: the storefront, a batch job, or someone in
# the query editor. The function deletes the matching cache keys; the next read
# repopulates them through cache-aside.
import json

import azure.functions as func

from shared.cache import cache

app = func.FunctionApp()


@app.sql_trigger(
    arg_name="changes",
    table_name="dbo.Products",
    connection_string_setting="SqlConnectionString",
)
def invalidate_products(changes: str) -> None:
    keys = {f"product:{c['Item']['ProductId']}" for c in json.loads(changes)}
    cache.delete(*keys)
    print(f"[sql-trigger] invalidated {sorted(keys)}", flush=True)
