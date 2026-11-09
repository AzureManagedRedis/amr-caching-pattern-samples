"""Azure Managed Redis client with Microsoft Entra ID auth (step 2 of the article).

The client is the article's: `redis.Redis` (the cache uses the Enterprise
clustering policy, so all connections use the cache hostname) with the
redis-entraid credential provider, which gets a token from
`DefaultAzureCredential` and reauthenticates open connections before the token
expires. The client verifies the certificate and checks that it matches the
cache hostname.

Why the client is created lazily: redis-entraid starts its token manager when the
client opens its first connection. If an asyncio event loop is running on that
thread, the token manager schedules its first token request on that loop and then
blocks the loop waiting for it, so the process hangs. Uvicorn imports this module
inside its running loop, so creating the client at import time would hang the app
at startup. Instead, `cache` is a small proxy that creates the real client on
first use, on a separate thread that has no running loop. Pattern code uses
`cache` exactly as the article does.
"""
import threading
from concurrent.futures import ThreadPoolExecutor

import redis
from redis_entraid.cred_provider import create_from_default_azure_credential

from .config import settings

_client: redis.Redis | None = None
_lock = threading.Lock()


def _create() -> redis.Redis:
    return redis.Redis(
        host=settings.redis_host,  # <name>.<region>.redis.azure.net
        port=settings.redis_port,
        ssl=True,
        ssl_check_hostname=True,  # The certificate must match the cache hostname.
        credential_provider=create_from_default_azure_credential(("https://redis.azure.com/.default",)),
        decode_responses=True,
    )


def get_client() -> redis.Redis:
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                # A fresh thread has no running event loop, so redis-entraid runs its own.
                with ThreadPoolExecutor(max_workers=1) as pool:
                    _client = pool.submit(_create).result()
    return _client


class _LazyCache:
    """Forwards every call to the Redis client, creating it on first use."""

    def __getattr__(self, name):
        return getattr(get_client(), name)


cache = _LazyCache()
