"""Fulfillment worker - Redis Streams consumer group.

Reads new messages from the orders stream (`>`), advances each order through
fulfillment states, writes each change to PostgreSQL, updates the cached
order-status view, then acks. A consumer group lets the work scale across
workers. (Recovering a crashed worker's in-flight messages would use XAUTOCLAIM;
not implemented here.)

Runs in-process (RUN_WORKER=true, the default) or standalone: `python -m app.worker`.
"""
import asyncio
import random

from redis.exceptions import TimeoutError as RedisTimeoutError

from . import azure_auth
from . import cache as cache_module
from . import db
from .cache import cache
from .config import settings
from .patterns.events import status_key

# Simulated fulfillment; each step waits a few seconds so progress is visible.
FULFILLMENT_STATES = ["paid", "packed", "shipped", "delivered"]
STEP_MIN_SECONDS = 3
STEP_MAX_SECONDS = 6
CONSUMER_NAME = "worker-1"


async def ensure_group() -> None:
    try:
        await cache().xgroup_create(
            settings.orders_stream, settings.orders_group, id="0", mkstream=True
        )
    except Exception as exc:  # noqa: BLE001 - group may already exist
        if "BUSYGROUP" not in str(exc):
            raise


async def _advance_order(order_id: int) -> None:
    for state in FULFILLMENT_STATES:
        await asyncio.sleep(random.uniform(STEP_MIN_SECONDS, STEP_MAX_SECONDS))
        await db.execute("UPDATE orders SET status = %s WHERE id = %s", (state, order_id))
        await cache().set(status_key(order_id), state, ex=settings.order_status_ttl_seconds)
        print(f"[worker] order {order_id} -> {state}", flush=True)


async def consume_forever() -> None:
    """Consume the stream. Assumes the db pool and cache are already open."""
    await ensure_group()
    print(
        f"[worker] consuming '{settings.orders_stream}' as group '{settings.orders_group}'",
        flush=True,
    )
    r = cache()
    while True:
        try:
            response = await r.xreadgroup(
                settings.orders_group,
                CONSUMER_NAME,
                {settings.orders_stream: ">"},
                count=10,
                block=5000,
            )
        except (RedisTimeoutError, asyncio.TimeoutError):
            # No new orders within the block window; keep waiting (this is normal idle).
            continue
        except Exception as exc:  # noqa: BLE001 - keep the worker alive across transient errors
            print(f"[worker] read error, retrying: {exc}", flush=True)
            await asyncio.sleep(1)
            continue
        if not response:
            continue
        for _stream, messages in response:
            for message_id, fields in messages:
                order_id = fields.get("order_id")
                try:
                    print(f"[worker] fulfilling order {order_id}", flush=True)
                    await _advance_order(int(order_id))
                    await r.xack(settings.orders_stream, settings.orders_group, message_id)
                except Exception as exc:  # noqa: BLE001 - keep the loop alive
                    print(f"[worker] failed to process order {order_id} ({message_id}): {exc}", flush=True)


async def _standalone() -> None:
    await db.open_pool()
    await cache_module.open_cache()
    try:
        await consume_forever()
    finally:
        await cache_module.close_cache()
        await db.close_pool()
        await azure_auth.close_credential()


if __name__ == "__main__":
    asyncio.run(_standalone())
