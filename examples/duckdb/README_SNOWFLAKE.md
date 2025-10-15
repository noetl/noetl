# DuckDB + Snowflake Integration Examples

This directory contains examples demonstrating how to use DuckDB's Snowflake extension within NoETL to query and transform Snowflake data.

## Overview

The integration enables you to:
- 🔗 **Connect** to Snowflake from DuckDB
- 📊 **Query** Snowflake tables directly
- 🔄 **Transform** data using DuckDB's analytical capabilities
- 💾 **Export** Snowflake data to local files (Parquet, CSV, etc.)
- 🔀 **Join** Snowflake data with local DuckDB tables
- 📤 **Load** transformed data back to Snowflake

## Quick Start

### 1. Setup Credentials

Edit `snowflake_credentials.yaml` with your Snowflake account details:

```yaml
- key: my_snowflake
  service: snowflake
  payload:
    account: "xy12345.us-east-1"  # Your Snowflake account
    user: "your_username"
    password: "your_password"
    warehouse: "COMPUTE_WH"
    database: "MY_DATABASE"
```

### 2. Register Credentials

```bash
.venv/bin/python -m noetl.main auth register \
  examples/duckdb/snowflake_credentials.yaml \
  --host localhost --port 8083
```

### 3. Run Example

```bash
# Register playbook
.venv/bin/python -m noetl.main catalog register \
  examples/duckdb/duckdb_snowflake_query.yaml \
  --host localhost --port 8083

# Execute
curl -X POST http://localhost:8083/api/executions/run \
  -H "Content-Type: application/json" \
  -d '{"path": "examples/duckdb_snowflake_query"}'
```

## Files in This Directory

### Credentials
- **`snowflake_credentials.yaml`** - Credential templates and examples
  - Test account credentials
  - Production credentials with env vars
  - Read-only account example
  - Alternative field naming

### Example Playbooks
- **`duckdb_snowflake_query.yaml`** - Simple query and export
  - Basic SELECT queries
  - Export to Parquet
  - Summary statistics

- **`duckdb_snowflake_etl.yaml`** - Complete ETL pipeline
  - Extract from Snowflake
  - Transform in DuckDB
  - Load back to Snowflake
  - Multi-step workflow

- **`duckdb_snowflake_join.yaml`** - Cross-source analytics
  - Cache Snowflake data locally
  - Join with local DuckDB tables
  - Performance optimization

### Documentation
- **`SNOWFLAKE_INTEGRATION.md`** - Complete integration guide (520+ lines)
  - Detailed setup instructions
  - Usage patterns and examples
  - Troubleshooting guide
  - Security best practices
  - Performance optimization tips

- **`SNOWFLAKE_QUICKSTART.md`** - Quick reference card
  - Command cheat sheet
  - Common patterns
  - Field mappings
  - Testing instructions

### Testing
- **`../test_duckdb_snowflake.sh`** - Integration test script
  - Validates Python imports
  - Checks credential format
  - Tests playbook syntax
  - Provides next steps

## Usage Patterns

### Pattern 1: Simple Query
```yaml
type: duckdb
auth:
  sf:
    type: snowflake
    credential: my_snowflake
with:
  commands: |
    INSTALL snowflake FROM community;
    LOAD snowflake;
    SELECT * FROM sf.MY_DB.PUBLIC.MY_TABLE LIMIT 10;
```

### Pattern 2: Export to Local File
```yaml
with:
  commands: |
    INSTALL snowflake FROM community;
    LOAD snowflake;
    COPY (SELECT * FROM sf.DB.SCHEMA.TABLE)
    TO '/tmp/export.parquet' (FORMAT PARQUET);
```

### Pattern 3: ETL Pipeline
```yaml
with:
  commands: |
    -- Extract
    CREATE TEMP TABLE staging AS
    SELECT * FROM sf_source.DB.SCHEMA.TABLE
    WHERE date >= CURRENT_DATE - 7;
    
    -- Transform
    UPDATE staging SET amount = amount * 1.1;
    
    -- Load
    INSERT INTO sf_target.DB.SCHEMA.TABLE
    SELECT * FROM staging;
```

### Pattern 4: Cross-Database Join
```yaml
auth:
  prod_sf:
    type: snowflake
    credential: snowflake_prod
  dev_sf:
    type: snowflake
    credential: snowflake_dev
with:
  commands: |
    SELECT p.*, d.test_results
    FROM prod_sf.PROD.PUBLIC.PRODUCTS p
    LEFT JOIN dev_sf.DEV.PUBLIC.TESTS d
      ON p.id = d.product_id;
```

## Credential Field Reference

| Field | Required | Description | Alternative Names |
|-------|----------|-------------|-------------------|
| `account` | ✓ | Snowflake account identifier | `sf_account` |
| `user` | ✓ | Username | `username`, `sf_user` |
| `password` | ✓ | Password | `sf_password` |
| `database` | | Default database | `sf_database` |
| `schema` | | Default schema | `sf_schema` |
| `warehouse` | | Compute warehouse | `sf_warehouse` |
| `role` | | User role | `sf_role` |

## How It Works

### 1. Credential Registration
When you register Snowflake credentials, NoETL stores them in the credential table with `service: snowflake`.

### 2. DuckDB Secret Generation
When a playbook uses Snowflake credentials, NoETL automatically generates a DuckDB `CREATE SECRET` statement:

```sql
CREATE OR REPLACE SECRET sf (
  TYPE snowflake,
  ACCOUNT 'xy12345.us-east-1',
  USER 'username',
  PASSWORD 'password',
  DATABASE 'MY_DB',
  WAREHOUSE 'COMPUTE_WH'
);
```

### 3. Extension Loading
The Snowflake extension is installed from DuckDB's community repository:

```sql
INSTALL snowflake FROM community;
LOAD snowflake;
```

### 4. Query Execution
Tables are accessed using the secret name as a prefix:

```sql
SELECT * FROM sf.DATABASE.SCHEMA.TABLE;
```

## Testing

Run the complete integration test:

```bash
./test_duckdb_snowflake.sh
```

This validates:
- ✅ Python imports
- ✅ Extension mapping
- ✅ Secret generation
- ✅ Credential definitions
- ✅ Playbook syntax

## Troubleshooting

### Extension Not Found
```sql
-- Manually install
INSTALL snowflake FROM community;
LOAD snowflake;
```

### Connection Failed
Check your credentials:
```bash
curl -s http://localhost:8083/api/credentials?key=my_snowflake
```

### Permission Denied
Verify Snowflake grants:
```sql
SHOW GRANTS TO ROLE your_role;
GRANT USAGE ON WAREHOUSE compute_wh TO ROLE your_role;
```

### Slow Queries
Use appropriate warehouse size:
```yaml
warehouse: "LARGE_WH"  # Instead of X-Small for large queries
```

## Security

✅ **DO**:
- Use environment variables for passwords
- Create service accounts with minimal permissions
- Rotate credentials regularly
- Use read-only roles where possible

❌ **DON'T**:
- Commit credentials to git
- Use personal accounts
- Share credentials across environments
- Use admin roles for ETL

## Performance Tips

1. **Cache dimension tables locally**
   ```sql
   CREATE TABLE local_dim AS
   SELECT * FROM sf.DB.SCHEMA.LARGE_DIM;
   ```

2. **Limit data transfer**
   ```sql
   WHERE date >= CURRENT_DATE - 7
   LIMIT 100000
   ```

3. **Use appropriate warehouses**
   - X-Small: Testing, small queries
   - Small/Medium: Regular workloads
   - Large/X-Large: Heavy ETL

4. **Export to Parquet for repeated use**
   ```sql
   COPY (...) TO 'cached_data.parquet';
   ```

## Examples Summary

| File | Use Case | Complexity |
|------|----------|------------|
| `duckdb_snowflake_query.yaml` | Simple queries | ⭐ Beginner |
| `duckdb_snowflake_etl.yaml` | ETL pipeline | ⭐⭐ Intermediate |
| `duckdb_snowflake_join.yaml` | Cross-source joins | ⭐⭐⭐ Advanced |

## Next Steps

1. ✅ Review credential templates
2. ✅ Update with your Snowflake details
3. ✅ Register credentials with NoETL
4. ✅ Run simple query example
5. ✅ Explore ETL pipeline example
6. ✅ Read complete integration guide

## Resources

- **DuckDB Snowflake Extension**: https://duckdb.org/community_extensions/extensions/snowflake.html
- **Complete Guide**: `SNOWFLAKE_INTEGRATION.md`
- **Quick Reference**: `SNOWFLAKE_QUICKSTART.md`
- **Snowflake Docs**: https://docs.snowflake.com/

## Support

For issues or questions:
1. Check `SNOWFLAKE_INTEGRATION.md` troubleshooting section
2. Run `./test_duckdb_snowflake.sh` for diagnostics
3. Review NoETL logs: `logs/worker.log`, `logs/server.log`
4. Verify credentials: `curl http://localhost:8083/api/credentials`

---

**Status**: ✅ Production Ready  
**Last Updated**: October 14, 2025  
**DuckDB Version**: 0.10.0+  
**Extension**: snowflake (community)
