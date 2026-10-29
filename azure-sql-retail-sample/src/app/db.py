"""Azure SQL Database access with mssql-python and Microsoft Entra ID auth.

mssql-python is the Microsoft Python driver for SQL Server and Azure SQL. It
doesn't need a separate ODBC driver, and `Authentication=ActiveDirectoryDefault`
gets a token from `DefaultAzureCredential`: the managed identity in Azure
(AZURE_CLIENT_ID) or your `az login` account locally. The driver pools
connections by default, so `get_db()` is cheap to call per operation.
"""
from mssql_python import connect

from .config import settings

SQL_CONNECTION_STRING = (
    f"Server=tcp:{settings.sql_server},1433;"
    f"Database={settings.sql_database};"
    "Encrypt=yes;TrustServerCertificate=no;"
    "Authentication=ActiveDirectoryDefault"
)


def get_db(autocommit: bool = False):
    return connect(SQL_CONNECTION_STRING, autocommit=autocommit)
