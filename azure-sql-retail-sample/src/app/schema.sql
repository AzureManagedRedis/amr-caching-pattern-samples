-- Retail cache sample schema for Azure SQL Database. Idempotent; batches are separated by GO.
IF OBJECT_ID(N'dbo.Categories') IS NULL
CREATE TABLE dbo.Categories (
    CategoryId INT IDENTITY PRIMARY KEY,
    Name       NVARCHAR(100) NOT NULL
);
GO
IF OBJECT_ID(N'dbo.Products') IS NULL
CREATE TABLE dbo.Products (
    ProductId   INT IDENTITY PRIMARY KEY,
    CategoryId  INT NOT NULL REFERENCES dbo.Categories(CategoryId),
    Name        NVARCHAR(200) NOT NULL,
    Brand       NVARCHAR(100) NOT NULL,
    Description NVARCHAR(500) NULL,
    ImageUrl    NVARCHAR(200) NULL,
    Price       DECIMAL(10,2) NOT NULL,
    Stock       INT NOT NULL
);
GO
IF OBJECT_ID(N'dbo.Reviews') IS NULL
CREATE TABLE dbo.Reviews (
    ReviewId  BIGINT IDENTITY PRIMARY KEY,
    ProductId INT NOT NULL REFERENCES dbo.Products(ProductId),
    Rating    TINYINT NOT NULL
);
GO
-- Starts empty. The write-behind flush adds rows.
IF OBJECT_ID(N'dbo.ProductStats') IS NULL
CREATE TABLE dbo.ProductStats (
    ProductId INT PRIMARY KEY REFERENCES dbo.Products(ProductId),
    Views     BIGINT NOT NULL DEFAULT 0
);
GO
-- Change tracking: the reference-data sync reads only changed categories, and the
-- Azure Functions SQL trigger requires it on dbo.Products.
IF NOT EXISTS (SELECT 1 FROM sys.change_tracking_databases WHERE database_id = DB_ID())
    ALTER DATABASE CURRENT SET CHANGE_TRACKING = ON (CHANGE_RETENTION = 2 DAYS, AUTO_CLEANUP = ON);
GO
IF NOT EXISTS (SELECT 1 FROM sys.change_tracking_tables WHERE object_id = OBJECT_ID(N'dbo.Categories'))
    ALTER TABLE dbo.Categories ENABLE CHANGE_TRACKING;
GO
IF NOT EXISTS (SELECT 1 FROM sys.change_tracking_tables WHERE object_id = OBJECT_ID(N'dbo.Products'))
    ALTER TABLE dbo.Products ENABLE CHANGE_TRACKING;
GO
-- The trigger stores its progress in lease tables in this schema.
IF SCHEMA_ID(N'az_func') IS NULL
    EXEC (N'CREATE SCHEMA az_func');
