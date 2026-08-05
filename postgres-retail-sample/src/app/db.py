"""PostgreSQL access with a connection pool and Microsoft Entra ID auth.

`EntraAsyncConnection` injects a fresh Entra access token as the password each
time the pool opens a new physical connection. `max_lifetime` recycles pooled
connections before the ~1 hour token lifetime, so the pool always holds
authenticated connections.

Queries use thin SQL through `psycopg`, the standard PostgreSQL adapter for
Python, so the caching logic stays front and center.
"""
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .azure_auth import PG_SCOPE, get_token
from .config import settings


class EntraAsyncConnection(psycopg.AsyncConnection):
    @classmethod
    async def connect(cls, conninfo: str = "", **kwargs):
        kwargs["password"] = await get_token(PG_SCOPE)
        return await super().connect(conninfo, **kwargs)


_pool: AsyncConnectionPool | None = None


def _base_kwargs() -> dict:
    return dict(
        host=settings.postgres_host,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        port=settings.postgres_port,
        sslmode="require",
        autocommit=True,
    )


async def open_pool() -> None:
    global _pool
    _pool = AsyncConnectionPool(
        connection_class=EntraAsyncConnection,
        kwargs=_base_kwargs(),
        min_size=1,
        max_size=10,
        max_lifetime=50 * 60,  # recycle before the Entra token expires
        open=False,
    )
    await _pool.open(wait=True)


async def close_pool() -> None:
    if _pool is not None:
        await _pool.close()


def pool() -> AsyncConnectionPool:
    assert _pool is not None, "Connection pool is not open. Call open_pool() first."
    return _pool


async def fetch_all(sql: str, params: tuple | None = None) -> list[dict]:
    async with pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        return await cur.fetchall()


async def fetch_one(sql: str, params: tuple | None = None) -> dict | None:
    async with pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        return await cur.fetchone()


async def execute(sql: str, params: tuple | None = None) -> None:
    async with pool().connection() as conn:
        await conn.execute(sql, params)
