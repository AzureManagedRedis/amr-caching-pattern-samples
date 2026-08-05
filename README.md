# AMR Caching Pattern Samples

Runnable samples that show how to put **Azure Managed Redis (AMR)** in front of different
Azure databases as a cache, using a shared set of caching patterns. Each sample is a
self-contained app you can deploy to Azure with a single `azd up`.

## Samples

| Sample | Database | What it shows |
| --- | --- | --- |
| [postgres-retail-sample](postgres-retail-sample/) | Azure Database for PostgreSQL flexible server | A retail storefront demonstrating four caching patterns with AMR as the cache |

Samples for other databases (for example, Azure SQL and Azure Cosmos DB) will follow the
same structure.

## Caching patterns

Every sample draws from the same vocabulary of patterns:

| Pattern | What it does |
| --- | --- |
| Cache-aside | Read from the cache first; on a miss, read the database and store the result for next time. |
| Reference-data prefetching | Proactively load stable, rarely-changing data into the cache so reads never hit the database; refresh when the source changes. |
| Write-through | Write to the database and the cache in the same operation, so the cache is never stale. |
| Event-driven | Publish changes as events; a worker updates the cached view, keeping it fresh without waiting for a TTL. |

Each sample's README shows how these patterns map to that database and application.

## Using a sample

1. Install [azd](https://aka.ms/azd-install) and the [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli), then sign in with `az login` and `azd auth login`.
2. Change into the sample folder, for example `cd postgres-retail-sample`.
3. Follow that sample's README to deploy (`azd up`) or run it locally.

Each sample provisions its own Azure resources and **bills while it runs**, so tear it down
with `azd down --purge --force` when you are finished.

## Repository layout

```
amr-caching-pattern-samples/
  postgres-retail-sample/   PostgreSQL + AMR retail storefront demonstrating four patterns
  LICENSE                   MIT license for the repository
  README.md                 This file
```

## Contributing

Contributions and suggestions are welcome. For anything substantial, open an issue to
discuss the change before sending a pull request.

Most contributions require you to agree to a Contributor License Agreement (CLA) declaring
that you have the right to, and actually do, grant us the rights to use your contribution.
For details, visit [cla.opensource.microsoft.com](https://cla.opensource.microsoft.com).
When you open a pull request, a CLA bot automatically tells you whether you need to sign;
you only do this once across all Microsoft repos.

## License

Licensed under the [MIT License](LICENSE). Individual samples may bundle third-party assets
(for example, product images from dotnet/eShop); see each sample's `ThirdPartyNotices.txt`
for attribution.

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized
use of Microsoft trademarks or logos is subject to and must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause
confusion or imply Microsoft sponsorship. Any use of third-party trademarks or logos is
subject to those third parties' policies.

## Support

This repository contains teaching samples, provided as-is and not officially supported by
Microsoft; they carry no warranties or SLAs. Please open an issue for questions or bugs.