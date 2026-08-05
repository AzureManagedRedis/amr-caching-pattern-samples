"""Configuration read from environment variables.

The app authenticates to both Azure Database for PostgreSQL and Azure Managed
Redis with Microsoft Entra ID (managed identity), whether it runs in Azure or
locally against those same resources.
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
    # PostgreSQL
    postgres_host: str = os.environ.get("POSTGRES_HOST", "localhost")
    postgres_db: str = os.environ.get("POSTGRES_DB", "retail")
    postgres_user: str = os.environ.get("POSTGRES_USER", "")
    postgres_port: int = int(os.environ.get("POSTGRES_PORT", "5432"))

    # Redis / Azure Managed Redis
    redis_host: str = os.environ.get("REDIS_HOST", "localhost")
    redis_port: int = int(os.environ.get("REDIS_PORT", "10000"))
    redis_username: str = os.environ.get("REDIS_USERNAME", "")

    # Behavior
    cache_ttl_seconds: int = int(os.environ.get("CACHE_TTL_SECONDS", "300"))
    order_status_ttl_seconds: int = int(os.environ.get("ORDER_STATUS_TTL_SECONDS", "604800"))  # 7 days
    orders_stream: str = os.environ.get("ORDERS_STREAM", "orders:events")
    orders_stream_maxlen: int = int(os.environ.get("ORDERS_STREAM_MAXLEN", "10000"))
    orders_group: str = os.environ.get("ORDERS_GROUP", "fulfillment")
    run_worker: bool = _bool("RUN_WORKER", "true")
    auto_seed: bool = _bool("AUTO_SEED", "true")


settings = Settings()
