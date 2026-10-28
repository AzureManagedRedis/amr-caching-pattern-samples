"""Configuration read from environment variables.

The app authenticates to both Azure SQL Database and Azure Managed Redis with
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
    # Azure SQL Database
    sql_server: str = os.environ.get("SQL_SERVER", "")  # for example myserver.database.windows.net
    sql_database: str = os.environ.get("SQL_DATABASE", "retail")

    # Azure Managed Redis
    redis_host: str = os.environ.get("REDIS_HOST", "localhost")
    redis_port: int = int(os.environ.get("REDIS_PORT", "10000"))
    redis_user_object_id: str = os.environ.get("REDIS_USER_OBJECT_ID", "")

    # Caching behavior
    product_ttl_seconds: int = int(os.environ.get("PRODUCT_TTL_SECONDS", "300"))
    not_found_ttl_seconds: int = int(os.environ.get("NOT_FOUND_TTL_SECONDS", "30"))
    sync_interval_seconds: int = int(os.environ.get("SYNC_INTERVAL_SECONDS", "30"))
    flush_interval_seconds: int = int(os.environ.get("FLUSH_INTERVAL_SECONDS", "15"))

    # The function app identity that seed.py grants SQL trigger permissions to.
    func_identity_name: str = os.environ.get("FUNC_IDENTITY_NAME", "")
    func_identity_client_id: str = os.environ.get("FUNC_IDENTITY_CLIENT_ID", "")
    # The developer who deployed the sample; seed.py gives them app-level access for running locally.
    developer_object_id: str = os.environ.get("DEVELOPER_OBJECT_ID", "")

    run_jobs: bool = _bool("RUN_JOBS", "true")
    auto_seed: bool = _bool("AUTO_SEED", "true")


settings = Settings()
