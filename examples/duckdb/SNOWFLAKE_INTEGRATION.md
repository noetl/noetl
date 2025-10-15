# DuckDB Snowflake Extension Integration

This guide explains how to use DuckDB's Snowflake extension within NoETL to query and transform Snowflake data.

## Overview

The DuckDB Snowflake extension allows you to:
- Query Snowflake tables directly from DuckDB
- Join Snowflake data with local DuckDB tables
- Export Snowflake data to local files
- Transform and load data back to Snowflake
- Use DuckDB's analytical capabilities on Snowflake data

**Extension Documentation**: https://duckdb.org/community_extensions/extensions/snowflake.html

## Prerequisites

1. **Snowflake Account**
   - Active Snowflake account with credentials
   - Database, schema, and warehouse access
   - Appropriate role permissions

2. **NoETL Setup**
   - NoETL server running
   - DuckDB plugin enabled
   - Credentials registered in credential table

## Credential Setup

### Step 1: Create Snowflake Credentials File

Create a YAML file with your Snowflake credentials:

```yaml
---
- key: snowflake_test
  service: snowflake
  payload:
    # Required fields
    account: "xy12345.us-east-1"      # Your Snowflake account identifier
    user: "your_username"              # Snowflake username
    password: "your_password"          # Snowflake password
    
    # Optional fields
    database: "ANALYTICS_DB"           # Default database
    schema: "PUBLIC"                   # Default schema
    warehouse: "COMPUTE_WH"            # Default warehouse
    role: "ANALYST_ROLE"               # Default role
```

**Finding Your Account Identifier**:
- Format: `<orgname>-<account_name>` or `<account_locator>.<region>`
- Found in Snowflake web UI URL or via `SELECT CURRENT_ACCOUNT()`
- Examples: `xy12345.us-east-1`, `orgname-accountname`

### Step 2: Register Credentials with NoETL

```bash
# Register credentials
.venv/bin/python -m noetl.main auth register \
  examples/duckdb/snowflake_credentials.yaml \
  --host localhost --port 8083

# Verify registration
curl -s http://localhost:8083/api/credentials | python3 -m json.tool
```

### Step 3: Test Connection

Create a simple test playbook:

```yaml
---
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: snowflake_connection_test
  path: examples/snowflake_test
workflow:
  - step: start
    type: duckdb
    auth:
      sf:
        type: snowflake
        credential: snowflake_test
    with:
      commands: |
        INSTALL snowflake FROM community;
        LOAD snowflake;
        SELECT CURRENT_ACCOUNT(), CURRENT_USER(), CURRENT_ROLE();
    next:
      - step: end
  - step: end
```

## Usage Examples

### Example 1: Simple Query

Query Snowflake data and display results:

```yaml
type: duckdb
auth:
  my_sf:
    type: snowflake
    credential: snowflake_test
with:
  commands: |
    INSTALL snowflake FROM community;
    LOAD snowflake;
    
    SELECT 
      customer_id,
      COUNT(*) as order_count,
      SUM(amount) as total_amount
    FROM my_sf.SALES_DB.PUBLIC.ORDERS
    WHERE order_date >= CURRENT_DATE - INTERVAL '30 days'
    GROUP BY customer_id
    ORDER BY total_amount DESC
    LIMIT 10;
```

### Example 2: Export to Parquet

Export Snowflake data to local Parquet files:

```yaml
type: duckdb
auth:
  sf:
    type: snowflake
    credential: snowflake_test
with:
  commands: |
    INSTALL snowflake FROM community;
    LOAD snowflake;
    
    COPY (
      SELECT * FROM sf.ANALYTICS_DB.PUBLIC.SALES
      WHERE sale_date >= '2025-01-01'
    ) TO '/tmp/sales_export.parquet' (FORMAT PARQUET);
```

### Example 3: Join Multiple Sources

Join Snowflake tables with different credentials:

```yaml
type: duckdb
auth:
  sf_prod:
    type: snowflake
    credential: snowflake_prod
  sf_dev:
    type: snowflake
    credential: snowflake_dev
with:
  commands: |
    INSTALL snowflake FROM community;
    LOAD snowflake;
    
    SELECT 
      p.product_name,
      p.category,
      d.test_results,
      d.test_date
    FROM sf_prod.CATALOG.PUBLIC.PRODUCTS p
    LEFT JOIN sf_dev.TESTING.PUBLIC.QA_TESTS d
      ON p.product_id = d.product_id
    WHERE d.test_date >= CURRENT_DATE - INTERVAL '7 days';
```

### Example 4: ETL Pipeline

Extract, transform, and load data:

```yaml
type: duckdb
auth:
  source:
    type: snowflake
    credential: snowflake_source
  target:
    type: snowflake
    credential: snowflake_target
with:
  commands: |
    INSTALL snowflake FROM community;
    LOAD snowflake;
    
    -- Extract and transform
    CREATE TEMP TABLE staging AS
    SELECT 
      customer_id,
      order_date,
      amount,
      amount * 0.9 as discounted_amount,
      DATE_TRUNC('month', order_date) as order_month
    FROM source.SALES.PUBLIC.ORDERS
    WHERE order_date >= CURRENT_DATE - INTERVAL '1 day';
    
    -- Load to target
    INSERT INTO target.ANALYTICS.PUBLIC.DAILY_SALES
    SELECT * FROM staging;
```

### Example 5: Cross-Database Analytics

Combine Snowflake data with local DuckDB analytics:

```yaml
type: duckdb
auth:
  sf:
    type: snowflake
    credential: snowflake_test
with:
  database: /tmp/analytics.db
  commands: |
    INSTALL snowflake FROM community;
    LOAD snowflake;
    
    -- Cache Snowflake data locally
    CREATE TABLE local_products AS
    SELECT * FROM sf.CATALOG.PUBLIC.PRODUCTS;
    
    -- Perform analytics on cached data
    SELECT 
      category,
      COUNT(*) as product_count,
      AVG(price) as avg_price,
      PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price) as median_price
    FROM local_products
    GROUP BY category;
```

## Credential Field Mapping

NoETL supports multiple field name variations:

| Standard Field | Alternative Fields | Required | Description |
|----------------|-------------------|----------|-------------|
| `account` | `sf_account` | ✓ | Snowflake account identifier |
| `user` | `username`, `sf_user` | ✓ | Snowflake username |
| `password` | `sf_password` | ✓ | Snowflake password |
| `database` | `sf_database` | | Default database |
| `schema` | `sf_schema` | | Default schema (default: PUBLIC) |
| `warehouse` | `sf_warehouse` | | Default warehouse |
| `role` | `sf_role` | | Default role |

## Generated DuckDB Secret

When you use Snowflake credentials, NoETL automatically generates a DuckDB `CREATE SECRET` statement:

```sql
CREATE OR REPLACE SECRET my_sf (
  TYPE snowflake,
  ACCOUNT 'xy12345.us-east-1',
  USER 'username',
  PASSWORD 'password',
  DATABASE 'ANALYTICS_DB',
  SCHEMA 'PUBLIC',
  WAREHOUSE 'COMPUTE_WH',
  ROLE 'ANALYST_ROLE'
);
```

The secret name (`my_sf`) becomes the prefix for accessing Snowflake tables:

```sql
SELECT * FROM my_sf.DATABASE.SCHEMA.TABLE;
```

## Advanced Patterns

### Pattern 1: Incremental Loads

```yaml
workload:
  last_load_date: "{{ 'now' | date('-1 day') }}"

workflow:
  - step: incremental_load
    type: duckdb
    auth:
      sf:
        type: snowflake
        credential: snowflake_test
    with:
      commands: |
        INSTALL snowflake FROM community;
        LOAD snowflake;
        
        CREATE TEMP TABLE new_records AS
        SELECT * 
        FROM sf.SALES.PUBLIC.TRANSACTIONS
        WHERE created_at >= '{{ workload.last_load_date }}'::TIMESTAMP;
        
        -- Process only new records
        SELECT COUNT(*) as new_record_count FROM new_records;
```

### Pattern 2: Multiple Warehouses

Use different warehouses for different operations:

```yaml
auth:
  sf_loading:
    type: snowflake
    credential: snowflake_load_wh  # Uses LOADING_WH
  sf_analytics:
    type: snowflake
    credential: snowflake_query_wh  # Uses ANALYTICS_WH
with:
  commands: |
    -- Use loading warehouse for writes
    INSERT INTO sf_loading.ETL.PUBLIC.STAGE_DATA
    SELECT * FROM source_data;
    
    -- Use analytics warehouse for queries
    SELECT * FROM sf_analytics.ANALYTICS.PUBLIC.REPORTS;
```

### Pattern 3: Dynamic Credentials

Use environment variables or secrets:

```yaml
- key: snowflake_dynamic
  service: snowflake
  payload:
    account: "{{ env.SNOWFLAKE_ACCOUNT }}"
    user: "{{ env.SNOWFLAKE_USER }}"
    password: "{{ secret.SNOWFLAKE_PASSWORD }}"
    warehouse: "{{ env.SNOWFLAKE_WAREHOUSE }}"
```

## Troubleshooting

### Connection Issues

**Problem**: `Failed to install snowflake extension`

```bash
# Solution 1: Manually install in DuckDB
INSTALL snowflake FROM community;
LOAD snowflake;

# Solution 2: Check DuckDB version (requires v0.10.0+)
SELECT version();
```

**Problem**: `Authentication failed`

```yaml
# Check credentials are correct
SELECT CURRENT_ACCOUNT(), CURRENT_USER();

# Verify credential registration
curl http://localhost:8083/api/credentials?key=snowflake_test
```

**Problem**: `Warehouse not found`

```sql
-- List available warehouses
SHOW WAREHOUSES;

-- Grant warehouse usage
GRANT USAGE ON WAREHOUSE COMPUTE_WH TO ROLE your_role;
```

### Performance Optimization

1. **Use appropriate warehouses**
   - Small queries: Use X-Small warehouse
   - Large ETL: Use Large or X-Large warehouse

2. **Cache dimension tables locally**
   ```sql
   CREATE TABLE local_dim AS
   SELECT * FROM sf.DB.SCHEMA.DIMENSION_TABLE;
   ```

3. **Limit data transfer**
   ```sql
   SELECT * FROM sf.DB.SCHEMA.LARGE_TABLE
   WHERE date >= CURRENT_DATE - INTERVAL '7 days'
   LIMIT 10000;
   ```

4. **Use Parquet for intermediate results**
   ```sql
   COPY (SELECT ...) TO 'temp_data.parquet';
   ```

## Security Best Practices

1. **Never commit credentials to git**
   ```bash
   echo "snowflake_credentials.yaml" >> .gitignore
   ```

2. **Use environment variables or secret managers**
   ```yaml
   password: "{{ secret.SNOWFLAKE_PASSWORD }}"
   ```

3. **Create service accounts**
   - Don't use personal credentials
   - Create dedicated service accounts with minimal permissions

4. **Rotate passwords regularly**
   - Update credentials in NoETL credential table
   - Test after rotation

5. **Use role-based access**
   ```sql
   CREATE ROLE NOETL_ROLE;
   GRANT SELECT ON ALL TABLES IN SCHEMA PUBLIC TO ROLE NOETL_ROLE;
   GRANT ROLE NOETL_ROLE TO USER noetl_service;
   ```

## Example Files

- `snowflake_credentials.yaml` - Credential templates
- `duckdb_snowflake_query.yaml` - Simple query example
- `duckdb_snowflake_etl.yaml` - Complete ETL pipeline
- `duckdb_snowflake_join.yaml` - Cross-source joins

## References

- [DuckDB Snowflake Extension](https://duckdb.org/community_extensions/extensions/snowflake.html)
- [NoETL Credential Management](../../docs/security/credentials.md)
- [DuckDB Plugin Documentation](../../docs/plugins/duckdb.md)
- [Snowflake Documentation](https://docs.snowflake.com/)

## Next Steps

1. Register your Snowflake credentials
2. Test connection with simple query
3. Run example playbooks
4. Build your own ETL pipelines
5. Monitor warehouse usage and costs
