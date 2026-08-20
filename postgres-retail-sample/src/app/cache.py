"""Azure Managed Redis client with Microsoft Entra ID auth.

`EntraCredentialProvider` supplies the (username, token) pair to redis-py. The
async client calls `get_credentials_async` and re-authenticates on reconnect, so
tokens are refreshed transparently. The username is the object (principal) ID of
the managed identity.

Clustering policy (why `RedisCluster`): in Azure the cache uses the OSS clustering
policy (see infra/resources.bicep), the configuration this sample highlights. It
exposes the Redis Cluster API, so the app uses a cluster-aware client
(`redis.asyncio.RedisCluster`) that discovers the shards and routes each key to
its slot. That is what gives the lowest latency and best throughput as the cache
scales out across shards.
"""
import redis.asyncio as redis
from redis.credentials import CredentialProvider

from .azure_auth import REDIS_SCOPE, get_token
from .config import settings


class EntraCredentialProvider(CredentialProvider):
    def __init__(self, username: str):
        self.username = username

    def get_credentials(self) -> tuple[str, str]:
        # Sync path, provided for completeness; the async client uses the async method below.
        from azure.identity import DefaultAzureCredential

        token = DefaultAzureCredential().get_token(REDIS_SCOPE).token
        return (self.username, token)

    async def get_credentials_async(self) -> tuple[str, str]:
        return (self.username, await get_token(REDIS_SCOPE))


_client: "redis.RedisCluster | None" = None


async def open_cache() -> None:
    global _client
    # Azure Managed Redis (OSS clustering policy): cluster API, TLS, Entra auth.
    # With OSS clustering the client discovers shards via CLUSTER SLOTS and connects
    # to each node by IP. AMR's certificate is issued for the cache FQDN, not the
    # per-node IPs, so hostname verification is disabled (ssl_check_hostname=False)
    # while the CA chain is still validated (ssl_cert_reqs stays 'required').
    _client = redis.RedisCluster(
        host=settings.redis_host,
        port=settings.redis_port,
        ssl=True,
        ssl_check_hostname=False,
        credential_provider=EntraCredentialProvider(settings.redis_username),
        decode_responses=True,
    )
    await _client.ping()


async def close_cache() -> None:
    if _client is not None:
        await _client.aclose()


def cache() -> "redis.RedisCluster":
    assert _client is not None, "Cache client is not open. Call open_cache() first."
    return _client
