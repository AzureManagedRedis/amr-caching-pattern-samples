"""Azure Managed Redis client with Microsoft Entra ID auth.

`EntraCredentialProvider` supplies the (username, token) pair to redis-py each
time the client opens a connection. The username is the object (principal) ID of
the identity. `DefaultAzureCredential` resolves the managed identity in Azure
(AZURE_CLIENT_ID) and your `az login` account locally.

Clustering policy (why `RedisCluster`): the cache uses the OSS clustering policy
(see infra/resources.bicep), so the app uses a cluster-aware client that routes
each key to its shard. Cluster redirects use node IP addresses, which the
certificate doesn't list, so hostname verification is off; the certificate chain
is still validated.

Tokens expire after about an hour. New connections always get a fresh token. For
long-lived connections in production, consider the redis-entraid package, which
reauthenticates open connections automatically.
"""
from azure.identity import DefaultAzureCredential
from redis.cluster import RedisCluster
from redis.credentials import CredentialProvider

from .config import settings

REDIS_SCOPE = "https://redis.azure.com/.default"

credential = DefaultAzureCredential()


class EntraCredentialProvider(CredentialProvider):
    """Supplies a fresh Microsoft Entra token to redis-py."""

    def __init__(self, credential, username):
        self._credential = credential
        self._username = username

    def get_credentials(self):
        token = self._credential.get_token(REDIS_SCOPE)
        return self._username, token.token


cache = RedisCluster(
    host=settings.redis_host,
    port=settings.redis_port,
    ssl=True,
    ssl_check_hostname=False,  # Cluster redirects use node IPs; the certificate is still verified.
    credential_provider=EntraCredentialProvider(credential, settings.redis_user_object_id),
    decode_responses=True,
)
