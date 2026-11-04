# function_app.py
import json
import azure.functions as func
from shared.cache import cache             # The RedisCluster client

app = func.FunctionApp()

# Invoked automatically when the SQL trigger detects order changes
@app.sql_trigger(
    arg_name="changes",
    table_name="dbo.Orders",
    connection_string_setting="SqlConnectionString",
)
def invalidate_order_status(changes: str) -> None:
    # 1. changes is a JSON list of changed rows. Build the cache key for each one.
    #    A set removes duplicates when the same order changed more than once.
    keys = {f"order:{c['Item']['OrderId']}:status" for c in json.loads(changes)}
    # 2. Delete those keys. The next read loads each status fresh from the database.
    #    Skip an empty batch, because DEL with no keys is an error in redis.Redis.
    if keys:
        cache.delete(*keys)
