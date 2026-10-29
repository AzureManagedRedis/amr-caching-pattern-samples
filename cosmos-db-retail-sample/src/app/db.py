"""Azure Cosmos DB client with Microsoft Entra ID auth (step 2 of the article).

`DefaultAzureCredential` resolves the managed identity in Azure (AZURE_CLIENT_ID)
and your `az login` account locally. Create the client once and reuse it; it
manages its own connection pool and renews tokens automatically.

The database and containers are created by the Bicep template, because a
data-plane role assignment can't create them.
"""
from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential

from .config import settings

credential = DefaultAzureCredential()

cosmos = CosmosClient(
    settings.cosmos_endpoint,  # https://<account>.documents.azure.com:443/
    credential=credential,
)
db = cosmos.get_database_client(settings.cosmos_database)
products = db.get_container_client("products")
orders = db.get_container_client("orders")
reference = db.get_container_client("reference")
