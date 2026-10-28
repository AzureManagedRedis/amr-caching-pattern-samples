"""Azure Managed Redis client for the function app, with Microsoft Entra ID auth.

Same client as the storefront (src/app/cache.py). In Azure, DefaultAzureCredential
uses the function's user-assigned identity (AZURE_CLIENT_ID), and
REDIS_USER_OBJECT_ID is that identity's object ID.
"""
import os

from azure.identity import DefaultAzureCredential
from redis.cluster import RedisCluster
from redis.credentials import CredentialProvider

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
    host=os.environ["REDIS_HOST"],
    port=int(os.environ.get("REDIS_PORT", "10000")),
    ssl=True,
    ssl_check_hostname=False,  # Cluster redirects use node IPs; the certificate is still verified.
    credential_provider=EntraCredentialProvider(credential, os.environ["REDIS_USER_OBJECT_ID"]),
    decode_responses=True,
)
