"""FastAPI entry point and storefront routes.

Each route is annotated with the caching pattern it demonstrates. The UI is a
self-contained Jinja2 storefront (templates/ and static/); you can ignore it and
focus on the pattern modules under app/patterns/.

Handlers are plain `def` functions, so FastAPI runs them in its thread pool and
the pattern code can use the synchronous azure-cosmos and redis-py clients, as
the article does. Startup work also runs on a worker thread; see cache.py for why
the Redis client must not be created on the event loop thread.
"""
import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import seed
from .config import settings
from .patterns import cache_aside, cart, external_writes, prefetch, ranking, write_through

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))
USER_COOKIE = "retail_user"


def _startup():
    if settings.auto_seed:
        seed.ensure_seeded()  # upsert the sample catalog and reference data if missing
    prefetch.load_all()  # reference-data prefetch at startup


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(_startup)
    yield


app = FastAPI(title="Retail cache sample", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


@app.middleware("http")
async def assign_user(request: Request, call_next):
    """Give each browser an anonymous ID for its cart (no sign-in in this sample)."""
    user_id = request.cookies.get(USER_COOKIE)
    is_new = not user_id
    request.state.user_id = user_id or uuid.uuid4().hex
    response = await call_next(request)
    if is_new:
        response.set_cookie(USER_COOKIE, request.state.user_id, httponly=True, samesite="lax")
    return response


def _listing(category_id: str | None) -> tuple[list[dict], str]:
    """Category listings through cache-aside. "All" combines every category page."""
    if category_id:
        return cache_aside.get_category_page(category_id)
    items, sources = [], set()
    for category in prefetch.get_reference("category"):
        page, source = cache_aside.get_category_page(category["id"])
        items += page
        sources.add(source)
    return items, "database" if "database" in sources else "cache"


def _cart_count(request: Request) -> int:
    return sum(cart.get_cart(request.state.user_id).values())


@app.get("/", response_class=HTMLResponse)
def index(request: Request, category: str | None = None, renamed: bool = False):
    start = time.perf_counter()
    products, source = _listing(category)  # cache-aside
    elapsed_ms = (time.perf_counter() - start) * 1000
    categories = prefetch.get_reference("category")  # served from the prefetched Redis hash
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "products": products,
            "source": source,
            "elapsed_ms": elapsed_ms,
            "categories": categories,
            "active_category": category,
            "renamed": renamed,
            "cart_count": _cart_count(request),
        },
    )


@app.get("/product/{category_id}/{product_id}", response_class=HTMLResponse)
def product_page(
    request: Request, category_id: str, product_id: str,
    updated: bool = False, restocked: bool = False, added: bool = False,
):
    start = time.perf_counter()
    product, source = cache_aside.get_product(category_id, product_id)  # cache-aside
    elapsed_ms = (time.perf_counter() - start) * 1000
    categories = {c["id"]: c["name"] for c in prefetch.get_reference("category")}
    return templates.TemplateResponse(
        request,
        "product.html",
        {
            "product": product,
            "category_name": categories.get(category_id, category_id),
            "source": source,
            "elapsed_ms": elapsed_ms,
            "updated": updated,
            "restocked": restocked,
            "added": added,
            "cart_count": _cart_count(request),
        },
        status_code=200 if product is not None else 404,
    )


@app.post("/product/{category_id}/{product_id}/price")
def set_price(category_id: str, product_id: str, price: float = Form(...)):
    write_through.update_price(category_id, product_id, round(price, 2))  # write-through
    return RedirectResponse(url=f"/product/{category_id}/{product_id}?updated=1", status_code=303)


@app.post("/product/{category_id}/{product_id}/restock")
def restock(category_id: str, product_id: str, quantity: int = Form(10)):
    external_writes.restock(category_id, product_id, quantity)  # Azure Cosmos DB only; the change feed refreshes
    return RedirectResponse(url=f"/product/{category_id}/{product_id}?restocked=1", status_code=303)


@app.post("/product/{category_id}/{product_id}/delete")
def soft_delete(category_id: str, product_id: str):
    external_writes.soft_delete(category_id, product_id)  # Azure Cosmos DB only; the change feed deletes the key
    return RedirectResponse(url=f"/?category={category_id}", status_code=303)


@app.post("/categories/rename")
def rename_category(category_id: str = Form(...), name: str = Form(...)):
    prefetch.rename_category(category_id, name.strip()[:100])  # the change feed updates the hash
    return RedirectResponse(url="/?renamed=1", status_code=303)


@app.post("/cart/add")
def add_to_cart(request: Request, category_id: str = Form(...), product_id: str = Form(...), quantity: int = Form(1)):
    cart.add_to_cart(request.state.user_id, category_id, product_id, max(quantity, 1))  # Redis only
    return RedirectResponse(url=f"/product/{category_id}/{product_id}?added=1", status_code=303)


def _cart_lines(user_id: str) -> list[dict]:
    lines = []
    for member, quantity in cart.get_cart(user_id).items():
        category_id, product_id = member.split(":", 1)
        product, _ = cache_aside.get_product(category_id, product_id)
        if product is not None:
            lines.append({"product": product, "quantity": quantity})
    return lines


@app.get("/cart", response_class=HTMLResponse)
def cart_page(request: Request, order: str | None = None, error: str | None = None):
    lines = _cart_lines(request.state.user_id)
    store = {i["id"]: i for i in prefetch.get_reference("config")}.get("store", {})
    return templates.TemplateResponse(
        request,
        "cart.html",
        {
            "lines": lines,
            "total": sum(line["product"]["price"] * line["quantity"] for line in lines),
            "shipping": prefetch.get_reference("shipping"),  # reference data from Redis
            "store": store,
            "checkout_id": uuid.uuid4().hex,  # idempotency key, generated once per checkout attempt
            "order": order,
            "error": error,
            "cart_count": sum(line["quantity"] for line in lines),
            "cart_ttl_minutes": settings.cart_ttl_seconds // 60,
        },
    )


@app.post("/checkout")
def checkout(request: Request, checkout_id: str = Form(...)):
    user_id = request.state.user_id
    try:
        # No sign-in in this sample, so the anonymous user ID is also the customer ID.
        order = cart.checkout(user_id, user_id, checkout_id)
    except ValueError as exc:
        return RedirectResponse(url=f"/cart?error={quote(str(exc))}", status_code=303)
    return RedirectResponse(url=f"/cart?order={order['id']}", status_code=303)


@app.get("/bestsellers", response_class=HTMLResponse)
def bestsellers(request: Request):
    rows = []
    for member, score in ranking.get_bestsellers(10):  # one ZREVRANGE
        category_id, product_id = member.split(":", 1)
        product, _ = cache_aside.get_product(category_id, product_id)
        if product is not None:
            rows.append({"product": product, "units": int(score)})
    return templates.TemplateResponse(
        request, "bestsellers.html", {"rows": rows, "cart_count": _cart_count(request)}
    )


@app.get("/api/category/{category_id}")
def category_api(category_id: str):
    start = time.perf_counter()
    items, source = cache_aside.get_category_page(category_id)
    return {"source": source, "elapsed_ms": round((time.perf_counter() - start) * 1000, 1), "items": items}


@app.get("/api/product/{category_id}/{product_id}")
def product_api(category_id: str, product_id: str):
    start = time.perf_counter()
    product, source = cache_aside.get_product(category_id, product_id)
    return {"source": source, "elapsed_ms": round((time.perf_counter() - start) * 1000, 1), "product": product}


@app.get("/api/reference/{ref_type}")
def reference_api(ref_type: str):
    return prefetch.get_reference(ref_type)


@app.get("/api/bestsellers")
def bestsellers_api(n: int = 10):
    return [{"member": member, "units": score} for member, score in ranking.get_bestsellers(n)]


@app.get("/api/cart")
def cart_api(request: Request):
    return cart.get_cart(request.state.user_id)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
