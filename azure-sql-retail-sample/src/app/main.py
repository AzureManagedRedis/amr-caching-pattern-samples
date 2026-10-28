"""FastAPI entry point and storefront routes.

Each route is annotated with the caching pattern it demonstrates. The UI is a
self-contained Jinja2 storefront (templates/ and static/); you can ignore it and
focus on the pattern modules under app/patterns/.

Handlers are plain `def` functions, so FastAPI runs them in its thread pool and
the pattern code can use the synchronous mssql-python and redis-py clients, as
the article does.
"""
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import jobs, seed
from .config import settings
from .db import get_db
from .patterns import cache_aside, invalidation, prefetch, write_behind, write_through

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_seed:
        seed.ensure_seeded()  # create schema, grant the function identity, seed the catalog
    prefetch.load_categories()  # reference-data prefetching at startup

    stop = jobs.start() if settings.run_jobs else None
    if stop is None:
        print("[jobs] disabled (RUN_JOBS=false)", flush=True)

    yield

    if stop is not None:
        stop.set()


app = FastAPI(title="Retail cache sample", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

CATALOG_SQL = "SELECT ProductId, Name, Brand, Price, ImageUrl FROM dbo.Products "


def _catalog(category_id: int | None) -> list[dict]:
    with get_db() as conn, conn.cursor() as cursor:
        if category_id is None:
            cursor.execute(CATALOG_SQL + "ORDER BY ProductId;")
        else:
            cursor.execute(CATALOG_SQL + "WHERE CategoryId = ? ORDER BY ProductId;", (category_id,))
        rows = cursor.fetchall()
    return [
        {"id": r.ProductId, "name": r.Name, "brand": r.Brand, "price": float(r.Price), "image_url": r.ImageUrl}
        for r in rows
    ]


@app.get("/", response_class=HTMLResponse)
def index(request: Request, category: int | None = None, renamed: bool = False):
    products = _catalog(category)
    categories = prefetch.get_categories()  # served from the prefetched Redis hash
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "products": products,
            "categories": categories,
            "active_category": category,
            "renamed": renamed,
            "sync_interval": settings.sync_interval_seconds,
        },
    )


@app.get("/product/{product_id}", response_class=HTMLResponse)
def product_page(request: Request, product_id: int, updated: bool = False, restocked: bool = False):
    start = time.perf_counter()
    product, source = cache_aside.get_product(product_id)  # cache-aside
    elapsed_ms = (time.perf_counter() - start) * 1000
    if product is not None:
        write_behind.record_view(product_id)  # write-behind
    return templates.TemplateResponse(
        request,
        "product.html",
        {
            "product": product,
            "source": source,
            "elapsed_ms": elapsed_ms,
            "updated": updated,
            "restocked": restocked,
            "pending_views": write_behind.pending_views().get(product_id, 0),
            "flush_interval": settings.flush_interval_seconds,
        },
        status_code=200 if product is not None else 404,
    )


@app.post("/product/{product_id}/price")
def set_price(product_id: int, price: float = Form(...)):
    write_through.update_price(product_id, price)  # write-through
    return RedirectResponse(url=f"/product/{product_id}?updated=1", status_code=303)


@app.post("/product/{product_id}/restock")
def restock(product_id: int, quantity: int = Form(10)):
    invalidation.restock(product_id, quantity)  # external write; the SQL trigger invalidates
    return RedirectResponse(url=f"/product/{product_id}?restocked=1", status_code=303)


@app.post("/categories/rename")
def rename_category(category_id: int = Form(...), name: str = Form(...)):
    prefetch.rename_category(category_id, name.strip()[:100])  # change tracking sync picks it up
    return RedirectResponse(url="/?renamed=1", status_code=303)


@app.get("/stats", response_class=HTMLResponse)
def stats(request: Request):
    pending = write_behind.pending_views()
    flushed = write_behind.flushed_views()
    rows = [
        {"id": p["id"], "name": p["name"], "flushed": flushed.get(p["id"], 0), "pending": pending.get(p["id"], 0)}
        for p in _catalog(None)
    ]
    return templates.TemplateResponse(
        request, "stats.html", {"rows": rows, "flush_interval": settings.flush_interval_seconds}
    )


@app.get("/api/product/{product_id}")
def product_api(product_id: int):
    start = time.perf_counter()
    product, source = cache_aside.get_product(product_id)
    return {"source": source, "elapsed_ms": round((time.perf_counter() - start) * 1000, 1), "product": product}


@app.get("/api/categories")
def categories_api():
    return prefetch.get_categories()


@app.get("/api/stats")
def stats_api():
    return {"flushed": write_behind.flushed_views(), "pending": write_behind.pending_views()}


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
