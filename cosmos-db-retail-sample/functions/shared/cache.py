"""Azure Managed Redis client for the function app.

This is the Redis client from step 2 of "Improve efficiency of reads by using
a cache with Azure Cosmos DB". The functions don't need an Azure Cosmos DB client:
the trigger delivers the changed items. In Azure, redis-entraid gets tokens from
`DefaultAzureCredential`, which uses the function's user-assigned identity
(AZURE_CLIENT_ID), and reads the Redis username (the identity's object ID) from
the token.

function_app.py imports this module inside each function, not at the top of the
file: see the note there.
"""
import os

import redis
from redis_entraid.cred_provider import create_from_default_azure_credential

cache = redis.Redis(
    host=os.environ["REDIS_HOST"],          # <name>.<region>.redis.azure.net
    port=int(os.environ.get("REDIS_PORT", "10000")),
    ssl=True,
    ssl_check_hostname=True,                # The certificate must match the cache hostname.
    credential_provider=create_from_default_azure_credential(("https://redis.azure.com/.default",)),
    decode_responses=True,
)
