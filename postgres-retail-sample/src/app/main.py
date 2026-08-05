"""FastAPI entry point and storefront routes.

Each route is annotated with the caching pattern it demonstrates. The UI is a
self-contained Jinja2 storefront (templates/ and static/); you can ignore it and
focus on the pattern modules under app/patterns/.
"""
import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import azure_auth
from . import cache as cache_module
from . import db, seed, worker
from .config import settings
from .db import fetch_all
from .patterns import cache_aside, events, prefetch, write_through

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))


def _log_worker_exit(task: asyncio.Task) -> None:
    """Surface a silent background-worker crash in the logs."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        import traceback

        print("[worker] stopped with an error:", flush=True)
        traceback.print_exception(type(exc), exc, exc.__traceback__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.open_pool()
    await cache_module.open_cache()
    if settings.auto_seed:
        await seed.ensure_seeded()  # create schema + seed catalog if empty
    await prefetch.prefetch_reference_data()  # reference-data prefetching at startup

    worker_task: asyncio.Task | None = None
    if settings.run_worker:
        worker_task = asyncio.create_task(worker.consume_forever())  # event-driven consumer
        worker_task.add_done_callback(_log_worker_exit)
    else:
        print("[worker] disabled (RUN_WORKER=false)", flush=True)

    yield

    if worker_task is not None:
        worker_task.cancel()
        await asyncio.gather(worker_task, return_exceptions=True)
    await cache_module.close_cache()
    await db.close_pool()
    await azure_auth.close_credential()


app = FastAPI(title="Retail cache sample", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

CATALOG_SQL = (
    "SELECT p.id, p.name, p.price::float AS price, b.name AS brand, "
    "c.name AS category, p.image_url "
    "FROM products p "
    "JOIN brands b ON p.brand_id = b.id "
    "JOIN categories c ON p.category_id = c.id "
)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, category: str | None = None):
    if category:
        products = await fetch_all(CATALOG_SQL + "WHERE c.name = %s ORDER BY p.id", (category,))
    else:
        products = await fetch_all(CATALOG_SQL + "ORDER BY p.id")
    categories = await prefetch.get_categories()  # served from prefetched cache
    return templates.TemplateResponse(
        request,
        "index.html",
        {"products": products, "categories": categories, "active_category": category},
    )


@app.get("/product/{product_id}", response_class=HTMLResponse)
async def product_page(request: Request, product_id: int, updated: bool = False):
    start = time.perf_counter()
    product, source = await cache_aside.get_product(product_id)  # cache-aside
    elapsed_ms = (time.perf_counter() - start) * 1000
    return templates.TemplateResponse(
        request,
        "product.html",
        {"product": product, "source": source, "elapsed_ms": elapsed_ms, "updated": updated},
    )


@app.post("/product/{product_id}/price")
async def set_price(product_id: int, price: float = Form(...)):
    await write_through.update_price(product_id, price)  # write-through
    return RedirectResponse(url=f"/product/{product_id}?updated=1", status_code=303)


@app.post("/orders")
async def create_order(product_id: int = Form(...), quantity: int = Form(1)):
    order_id = await events.place_order(product_id, quantity)  # event-driven
    return RedirectResponse(url=f"/orders/{order_id}", status_code=303)


@app.get("/orders/{order_id}", response_class=HTMLResponse)
async def order_page(request: Request, order_id: int):
    status = await events.get_order_status(order_id)
    return templates.TemplateResponse(
        request, "order.html", {"order_id": order_id, "status": status}
    )


@app.get("/api/orders/{order_id}")
async def order_status_api(order_id: int):
    return JSONResponse({"order_id": order_id, "status": await events.get_order_status(order_id)})


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
