"""Microsoft Entra ID token acquisition for PostgreSQL and Azure Managed Redis.

`DefaultAzureCredential` resolves a managed identity in Azure and your developer
credential (Azure CLI, VS Code) locally. It caches tokens internally, so calling
`get_token` per connection is cheap and always returns a valid, unexpired token.
"""
from azure.identity.aio import DefaultAzureCredential

# Entra ID resource scopes.
PG_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"
REDIS_SCOPE = "https://redis.azure.com/.default"

_credential = DefaultAzureCredential()


async def get_token(scope: str) -> str:
    token = await _credential.get_token(scope)
    return token.token


async def close_credential() -> None:
    await _credential.close()
