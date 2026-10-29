"""Configuration read from environment variables.

The app authenticates to both Azure Cosmos DB and Azure Managed Redis with
Microsoft Entra ID (managed identity), whether it runs in Azure or locally
against those same resources.
"""
import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv

    load_dotenv()  # load a local .env file if present (local development)
except ImportError:
    pass


def _bool(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() == "true"


@dataclass(frozen=True)
class Settings:
    # Azure Cosmos DB for NoSQL
    cosmos_endpoint: str = os.environ.get("COSMOS_ENDPOINT", "")  # https://<account>.documents.azure.com:443/
    cosmos_database: str = os.environ.get("COSMOS_DATABASE", "retail")

    # Azure Managed Redis
    redis_host: str = os.environ.get("REDIS_HOST", "localhost")
    redis_port: int = int(os.environ.get("REDIS_PORT", "10000"))

    # Caching behavior (the article's defaults)
    category_ttl_seconds: int = int(os.environ.get("CATEGORY_TTL_SECONDS", "120"))
    product_ttl_seconds: int = int(os.environ.get("PRODUCT_TTL_SECONDS", "300"))
    not_found_ttl_seconds: int = int(os.environ.get("NOT_FOUND_TTL_SECONDS", "30"))
    cart_ttl_seconds: int = int(os.environ.get("CART_TTL_SECONDS", "1800"))
    # How long a soft-deleted product stays in Azure Cosmos DB before TTL removes it.
    soft_delete_ttl_seconds: int = int(os.environ.get("SOFT_DELETE_TTL_SECONDS", "3600"))

    auto_seed: bool = _bool("AUTO_SEED", "true")


settings = Settings()
