# DuckDB Snowflake Extension - Quick Reference

## Installation Status
✅ Snowflake extension support added to NoETL DuckDB plugin

## Files Added
- `examples/duckdb/snowflake_credentials.yaml` - Credential templates
- `examples/duckdb/duckdb_snowflake_query.yaml` - Simple query example
- `examples/duckdb/duckdb_snowflake_etl.yaml` - ETL pipeline example
- `examples/duckdb/duckdb_snowflake_join.yaml` - Cross-source join example
- `examples/duckdb/SNOWFLAKE_INTEGRATION.md` - Complete documentation
- `test_duckdb_snowflake.sh` - Integration test script

## Code Changes
1. **types.py**: Added `SNOWFLAKE = "snowflake"` to AuthType enum
2. **extensions.py**: Added Snowflake to `AUTH_TYPE_EXTENSIONS` mapping
3. **extensions.py**: Added Snowflake to critical extensions list
4. **extensions.py**: Added Snowflake case in `install_database_extensions()`
5. **auth/secrets.py**: Added `_generate_snowflake_secret()` function

## Quick Start

### 1. Setup Credentials
```yaml
- key: my_snowflake
  service: snowflake
  payload:
    account: "xy12345.us-east-1"
    user: "your_username"
    password: "your_password"
    warehouse: "COMPUTE_WH"
    database: "MY_DB"
```

### 2. Register Credentials
```bash
.venv/bin/python -m noetl.main auth register \
  snowflake_credentials.yaml --host localhost --port 8083
```

### 3. Use in Playbook
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

## DuckDB Secret Format

NoETL automatically generates:

```sql
CREATE OR REPLACE SECRET sf (
  TYPE snowflake,
  ACCOUNT 'xy12345.us-east-1',
  USER 'username',
  PASSWORD 'password',
  DATABASE 'MY_DB',
  SCHEMA 'PUBLIC',
  WAREHOUSE 'COMPUTE_WH',
  ROLE 'MY_ROLE'
);
```

## Usage Patterns

### Query Snowflake
```sql
SELECT * FROM sf.DATABASE.SCHEMA.TABLE;
```

### Export to Local
```sql
COPY (SELECT * FROM sf.DB.SCHEMA.TABLE)
TO '/tmp/data.parquet' (FORMAT PARQUET);
```

### Join with Local Data
```sql
SELECT *
FROM local_table l
JOIN sf.DB.SCHEMA.remote_table r
  ON l.id = r.id;
```

### Load to Snowflake
```sql
INSERT INTO sf.DB.SCHEMA.TARGET_TABLE
SELECT * FROM local_staging_table;
```

## Field Name Mapping

| Standard | Alternatives | Required |
|----------|-------------|----------|
| account | sf_account | ✓ |
| user | username, sf_user | ✓ |
| password | sf_password | ✓ |
| database | sf_database | |
| schema | sf_schema | |
| warehouse | sf_warehouse | |
| role | sf_role | |

## Testing

Run the integration test:
```bash
./test_duckdb_snowflake.sh
```

## References

- **DuckDB Extension**: https://duckdb.org/community_extensions/extensions/snowflake.html
- **Complete Guide**: `examples/duckdb/SNOWFLAKE_INTEGRATION.md`
- **Example Playbooks**: `examples/duckdb/duckdb_snowflake_*.yaml`

## Troubleshooting

### Extension Installation
```sql
-- Manual installation
INSTALL snowflake FROM community;
LOAD snowflake;
```

### Connection Test
```sql
SELECT CURRENT_ACCOUNT(), CURRENT_USER(), CURRENT_ROLE();
```

### List Available Objects
```sql
SHOW DATABASES;
SHOW SCHEMAS IN DATABASE my_db;
SHOW TABLES IN SCHEMA my_db.public;
```

## Next Steps

1. ✅ Test basic Snowflake connection
2. ✅ Run example query playbook
3. ✅ Build ETL pipeline
4. ✅ Monitor warehouse usage
5. ✅ Optimize query performance
