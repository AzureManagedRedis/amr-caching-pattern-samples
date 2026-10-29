"""Azure Managed Redis and Azure Cosmos DB clients for the function app.

This is the code from step 2 of "Optimize costs by using a cache with Azure
Cosmos DB for NoSQL", plus `clean()` from step 3, as the article's step 6
describes. In Azure, `DefaultAzureCredential` uses the function's user-assigned
identity (AZURE_CLIENT_ID), and redis-entraid reads the Redis username (the
identity's object ID) from the token.

function_app.py imports this module inside each function, not at the top of the
file: see the note there.
"""
import os

from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential
from redis.cluster import RedisCluster
from redis_entraid.cred_provider import create_from_default_azure_credential

credential = DefaultAzureCredential()

cosmos = CosmosClient(
    os.environ["COSMOS_ENDPOINT"],          # https://<account>.documents.azure.com:443/
    credential=credential,
)
db = cosmos.get_database_client("retail")
products = db.get_container_client("products")
orders = db.get_container_client("orders")
reference = db.get_container_client("reference")

cache = RedisCluster(
    host=os.environ["REDIS_HOST"],          # <name>.<region>.redis.azure.net
    port=10000,
    ssl=True,
    ssl_check_hostname=False,               # Cluster nodes are addressed by IP. The certificate is still validated.
    credential_provider=create_from_default_azure_credential(("https://redis.azure.com/.default",)),
    decode_responses=True,
)

SYSTEM_PROPERTIES = ("_rid", "_self", "_etag", "_attachments", "_ts", "_lsn")


def clean(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in SYSTEM_PROPERTIES}
