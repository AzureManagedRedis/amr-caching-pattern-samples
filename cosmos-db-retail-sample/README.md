# Retail cache sample: Caching patterns for Azure Cosmos DB for NoSQL

A small retail storefront that demonstrates six caching patterns with **Azure Cosmos
DB for NoSQL** as the source of truth and **Azure Managed Redis** as the cache. Both
authenticate with **Microsoft Entra ID** (managed identity), so there are no keys or
passwords in the deployed app.

This sample is the runnable companion to the Microsoft Learn article
[Improve efficiency of reads by using a cache with Azure Cosmos DB](https://learn.microsoft.com/azure/cosmos-db/how-to-cache). Most pattern modules
match a step in that article. Reference-data prefetching and the cart are extras
that the article lists in its caching patterns table but doesn't walk through.
The sample also adds code that the article describes but doesn't show: the
order-status cache-aside read and a **Ship order** button that simulates the
warehouse (both in `order_status.py`), and the complete best-sellers function. It
also adds a category rename, which updates the prefetched reference data
(`prefetch.py`).

> Part of [amr-caching-pattern-samples](../README.md). Run the commands in this README
> from the `cosmos-db-retail-sample/` folder.

## Patterns

How the caching patterns (see the [repository README](../README.md#caching-patterns)
for what each one is) map to this storefront:

| Pattern | Storefront feature | Azure Cosmos DB + Redis mechanism |
| --- | --- | --- |
| Cache-aside | Category listings and product pages | Single-partition query or point read on a miss, `SET` with a jittered TTL, short-lived "not found" entries |
| Reference-data prefetching | Category chips, shipping options, store settings | `reference` container loaded into Redis hashes at startup, kept current from the change feed |
| Write-through | Price updates | Patch the item in Azure Cosmos DB, then cache the item the patch returns |
| Event-driven refresh | Order status | Azure Functions trigger for Azure Cosmos DB writes the new status to cached order statuses with `SET XX KEEPTTL` when the warehouse ships an order |
| Sorted-set ranking | Best sellers | Azure Functions trigger on `orders` adds quantities with `ZINCRBY`; the page reads one `ZREVRANGE` |
| Session and state offload | Shopping cart | Redis hash with a sliding TTL; checkout writes one order with an idempotency key |

## Architecture

```mermaid
flowchart LR
    U[Shopper] --> W[FastAPI web app]
    W -->|cache-aside, prefetch, write-through, cart, ranking reads| R[(Azure Managed Redis)]
    W -->|source of truth| C[(Azure Cosmos DB for NoSQL)]
    C -->|change feed: orders, reference| F[Function app: Azure Cosmos DB triggers]
    F -->|SET order status, ZINCRBY, HSET ref| R
```

## See the patterns in action

Open the running app (the URL `azd` prints as `SERVICE_WEB_URI`, or
`http://localhost:8000` when [running locally](#run-locally)). Each pattern maps to
something you can do in the storefront.

- **Cache-aside: listings and product pages.** The catalog shows each category's
  top-rated products. The first request for a category is a miss, so the app runs a
  single-partition query and caches the result (key `category:<categoryId>:top`); a
  reload shows **Listing served from Redis cache**. Open any product
  (`/product/<categoryId>/<id>`): the first request point-reads the item and caches it
  (key `product:<categoryId>:<id>`), and reloads show **Served from Redis cache**. Each
  product stores its category name next to the category ID, so the page gets
  everything it shows from that one read. A
  product that doesn't exist is cached briefly as "not found" so repeated requests
  don't cost RUs. See [`cache_aside.py`](src/app/patterns/cache_aside.py).
- **Reference-data prefetching: category chips.** Categories, shipping options, and
  store settings are loaded from the `reference` container into the Redis hashes
  `ref:category`, `ref:shipping`, and `ref:config` at startup, with no TTL. Only one
  app replica loads at a time, and a hash that's already cached isn't reloaded, so a
  restart can't overwrite a newer value from the change feed. On the
  home page, expand **Rename a category** and save. The rename goes only to Azure
  Cosmos DB; the `refresh_reference` function reads it from the change feed and
  writes it with `HSET`, so the chip changes within seconds. Because products store
  the category name too, the app also updates that category's products in their
  single partition and caches each updated product (write-through). See
  [`prefetch.py`](src/app/patterns/prefetch.py),
  [`write_through.py`](src/app/patterns/write_through.py), and
  [`functions/function_app.py`](functions/function_app.py).
- **Write-through: price updates.** On a product page, expand **Update price
  (write-through)** and save. The app patches the price in Azure Cosmos DB, caches the
  item that the patch returns, and deletes the category listing, so the new price
  shows immediately and the page is still served from Redis. See
  [`write_through.py`](src/app/patterns/write_through.py).
- **Event-driven refresh: order status.** Check out a cart (below). The order page
  caches the status (`placed`) in `order:<customerId>:<id>:status` with a long TTL
  (`ORDER_STATUS_TTL_SECONDS`, one hour by default) and shows whether each read came
  from Redis or Azure Cosmos DB. Click **Ship order**. This patches the order in Azure
  Cosmos DB directly and doesn't touch Redis, the way a warehouse system would. The
  `refresh_order_status` function reads the change feed on `orders` and writes the new
  status to the cached key with `SET ... XX KEEPTTL`, usually within a few seconds, so
  the next read returns `shipped` from the cache instead of serving `placed` for up to
  an hour. The page checks the status every 2 seconds until `shipped` appears. See
  [`order_status.py`](src/app/patterns/order_status.py) and
  [`functions/function_app.py`](functions/function_app.py).
- **Sorted-set ranking: best sellers.** Check out a cart, then open **Best
  sellers**. The `update_bestsellers` function reads the change feed on `orders` and
  adds each line's quantity to the sorted set `bestsellers` with `ZINCRBY`, counting
  each order once. The page reads the top 10 with one `ZREVRANGE`. See
  [`ranking.py`](src/app/patterns/ranking.py).
- **Session and state offload: the cart.** **Add to cart** updates the Redis hash
  `cart:<user>` and resets its 30-minute TTL; it costs no RUs. **Check out** reads
  current prices from Azure Cosmos DB and writes one order whose ID is the checkout ID,
  then deletes the cart and opens the order page. Submitting the same checkout twice
  returns the existing order instead of creating a second one. See [`cart.py`](src/app/patterns/cart.py).

## Deploy to Azure

Prerequisites:
- [azd](https://aka.ms/azd-install)
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)
- An Azure subscription
- Permissions to create resources **and role assignments**: **Owner**, or
  **Contributor + Role Based Access Control Administrator** (the template assigns
  roles to the app and function identities, which Contributor alone can't do)
- Python 3.10 or later (only needed to run locally)

```bash
azd auth login
azd up
```

The template creates the `retail` database and its containers (`products`, `orders`,
`reference`, and `leases`), because a data-plane role can't create them. On first
start the web app seeds the catalog and reference data and loads the reference
hashes, so the storefront is ready as soon as `azd` finishes.

> TIP: If `azd up` fails on a resource, try redeploying in a different region:
> `azd down --purge --force`, then `azd env set AZURE_LOCATION <region>` and `azd up`.

### What gets provisioned

**This bills while it runs**, so tear it down when you are done.

| Resource | SKU / tier |
| --- | --- |
| Azure Managed Redis | `Balanced_B0`, Enterprise clustering policy, Entra-only auth |
| Azure Cosmos DB for NoSQL account | Serverless, local (key) auth disabled |
| Azure Container Apps environment + web app | Consumption, 1-3 replicas |
| Azure Functions app (Azure Cosmos DB triggers) | Linux App Service plan `B1`, Python 3.12 |
| Storage account (Functions runtime) | `Standard_LRS` |
| Azure Container Registry | `Basic` |
| User-assigned managed identities (web app, function app) | - |

Prices:
[Azure Managed Redis](https://azure.microsoft.com/pricing/details/managed-redis/),
[Azure Cosmos DB](https://azure.microsoft.com/pricing/details/cosmos-db/serverless/),
[Azure Container Apps](https://azure.microsoft.com/pricing/details/container-apps/),
[Azure Functions](https://azure.microsoft.com/pricing/details/functions/)

### Tear it down

```bash
azd down --purge --force
```

`--purge` also purges any soft-deleted resources (several Azure services keep a
recoverable copy after delete) so nothing lingers or keeps billing.

## Run locally

Run the app on your machine against the Azure resources you deployed. The app
authenticates as your `az login` account. During `azd up`, the template already gave
your account the **Cosmos DB Built-in Data Contributor** role and a Redis access
policy assignment, so you only need to let your IP through the Azure Cosmos DB
firewall. The account accepts connections only from Azure datacenters (the IP rule
`0.0.0.0`), which covers the deployed web app and function app.

Get `<resource-group>`, `<cosmos-account>`, `<amr-name>`, and `<region>` from
`azd env get-values` (`AZURE_RESOURCE_GROUP`, `COSMOS_ACCOUNT`, and `REDIS_HOST`).

`--ip-range-filter` replaces the whole list, so keep `0.0.0.0` in it, or the deployed
apps lose access:

```powershell
$ip = Invoke-RestMethod https://api.ipify.org
az cosmosdb update `
  --resource-group <resource-group> `
  --name <cosmos-account> `
  --ip-range-filter "0.0.0.0,$ip"
```

The update can take a few minutes. Running `azd provision` or `azd up` again resets
the list to `0.0.0.0`, so rerun this command afterward. For more options, see
[Configure IP firewall in Azure Cosmos DB](https://learn.microsoft.com/azure/cosmos-db/how-to-configure-firewall).

Then run the app:

```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:COSMOS_ENDPOINT = "https://<cosmos-account>.documents.azure.com:443/"
$env:COSMOS_DATABASE = "retail"
$env:REDIS_HOST = "<amr-name>.<region>.redis.azure.net"
$env:REDIS_PORT = "10000"
$env:AUTO_SEED = "false"
uvicorn app.main:app --app-dir src --reload --reload-dir src
```

`AUTO_SEED=false` is recommended locally because the deployed app already seeded the
shared account. The Azure Cosmos DB triggers run in the deployed function app, so
renames, shipped orders, and new orders from your local app still update the cache.

Open http://localhost:8000 and try the patterns above. (You can also copy
`.env.example` to `.env` and fill in the same values instead of setting environment
variables.)

## Least-privilege in production

The web app, the function app, and your developer account get only the **Cosmos DB
Built-in Data Contributor** role, which reads and writes items but can't create or
change databases, containers, or settings. That's why the template, not the app,
creates the database and containers, including the `leases` container that the
Azure Functions trigger would otherwise try to create. In production, consider a
[custom role definition](https://learn.microsoft.com/azure/cosmos-db/how-to-connect-role-based-access-control)
scoped to the containers each identity uses, for example read-only access to
`reference` for the web app. For the built-in roles and the data actions a custom
role can grant,
[see the data plane security reference.](https://learn.microsoft.com/azure/cosmos-db/nosql/reference-data-plane-security)

## Layout

```
src/app/
  main.py            FastAPI app + storefront routes (each tagged with its pattern)
  config.py          Environment settings
  db.py              azure-cosmos client with Entra auth (DefaultAzureCredential)
  cache.py           redis-py Redis client with redis-entraid, created on first use
  seed.py            Sample catalog and reference data (upserts missing items only)
  patterns/          The caching patterns (the teaching core)
  templates/, static/  Self-contained storefront UI
functions/
  function_app.py    Azure Cosmos DB triggers: order status, best sellers, reference data
  shared/cache.py    The article's step 2 Redis client
infra/               Bicep (Container Apps, Azure Cosmos DB, Azure Managed Redis, Functions)
```

## Notes

- **Clustering:** Azure Managed Redis uses the **Enterprise clustering policy**. The
  cache routes each key to its shard behind one endpoint, so the app connects with the
  standard `redis.Redis` client and verifies that the TLS certificate matches the cache
  hostname. The OSS clustering policy redirects clients to shard nodes by IP address,
  which the certificate doesn't list, so cluster clients must turn off hostname
  verification; if you use it, connect only through a private endpoint. Each pipeline
  in the sample uses `transaction=False`: the commands are sent together but don't
  run as one transaction, so keys on different shards need no hash tags.
- **Why the Redis client is created lazily:** the redis-entraid credential provider
  requests its first token on the thread that opens the first connection. If an
  asyncio event loop is running on that thread, it blocks the loop while waiting for
  a token that the loop itself must fetch, so the process hangs. Uvicorn imports the
  app inside its event loop, so [`cache.py`](src/app/cache.py) creates the client on
  first use, on a separate thread. For the same reason, each function in
  [`function_app.py`](functions/function_app.py) imports `shared.cache` inside its
  body, as the article does.
- **Change feed and deletes:** the triggers read the change feed in latest version
  mode, which doesn't include deletes or TTL expirations. Orders change status but
  aren't deleted, so the order-status refresh doesn't need them. For data that's
  deleted, mark items as deleted with a flag instead, and remove the cached entry
  when the function sees the flag.
- **Change feed latency:** after the trigger processes all current changes, it waits
  5 seconds by default (`feed_poll_delay`) before it polls again, so cache updates
  from other writers typically land within a few seconds.
- **No sign-in:** each browser gets an anonymous ID in a cookie, which the sample uses
  as both the cart owner and the order's `customerId` partition key value, so you can
  open only your own orders.
- **UI assets:** the catalog data and product images come from the MIT-licensed
  [dotnet/eShop](https://github.com/dotnet/eShop) sample, bundled under
  `src/app/static/img/`. Swap them by editing `PRODUCTS` in `seed.py`.

## License

This sample is part of [amr-caching-pattern-samples](../README.md) and is licensed under
the [MIT License](../LICENSE). It bundles catalog data and product images from the
MIT-licensed [dotnet/eShop](https://github.com/dotnet/eShop); see
[ThirdPartyNotices.txt](ThirdPartyNotices.txt) for attribution.
