# Snowflake Examples for NoETL

This directory contains example playbooks and configurations for using Snowflake with NoETL.

## Files

- **`snowflake_simple.yaml`** - Simple connection test playbook
- **`snowflake_test.yaml`** - Comprehensive test with DDL, DML, and queries
- **`snowflake_credentials.yaml`** - Template for credential configuration
- **`SETUP_GUIDE.md`** - Complete setup instructions

## Quick Start

### 1. Prerequisites

```bash
# Install NoETL with Snowflake support
task install-dev

# Start NoETL server
task noetl:local:start
```

### 2. Configure Snowflake Credentials

Edit `snowflake_credentials.yaml` with your Snowflake account details:

```yaml
credentials:
  - key: sf_test
    type: snowflake
    data:
      account: "YOUR_ACCOUNT.us-east-1"  # e.g., xy12345.us-east-1
      user: "YOUR_USERNAME"
      password: "YOUR_PASSWORD"
      warehouse: "COMPUTE_WH"
```

Register credentials:

```bash
.venv/bin/python -m noetl.main auth register \
  examples/snowflake/snowflake_credentials.yaml \
  --host localhost --port 8083
```

### 3. Register and Run Test Playbooks

```bash
# Register simple test
.venv/bin/python -m noetl.main catalog register \
  examples/snowflake/snowflake_simple.yaml \
  --host localhost --port 8083

# Run simple test
curl -X POST http://localhost:8083/api/executions/run \
  -H "Content-Type: application/json" \
  -d '{"path": "examples/snowflake_simple"}'

# Check results
curl -s http://localhost:8083/api/executions?path=examples/snowflake_simple \
  | python3 -m json.tool
```

## Example Playbooks

### snowflake_simple.yaml

Basic connection test that:
- Tests Snowflake connectivity
- Shows current session information
- Demonstrates parameter substitution

**Use this to verify your Snowflake setup is working.**

### snowflake_test.yaml

Comprehensive test that demonstrates:
- Database and schema creation
- Table creation with various Snowflake data types
- Working with VARIANT (JSON) and ARRAY types
- Data insertion with parameters
- Complex queries with JSON extraction
- Data updates
- Warehouse operations
- Cleanup

**Use this to learn Snowflake features and test full workflow.**

## Snowflake Account Requirements

To use these examples, you need:

1. **Snowflake Account** - Free trial available at https://signup.snowflake.com/
2. **User Credentials** - Username and password
3. **Warehouse Access** - At least one warehouse (e.g., COMPUTE_WH)
4. **Database Access** - Permission to create databases/schemas or access to existing one

See **`SETUP_GUIDE.md`** for detailed setup instructions.

## Common Use Cases

### Execute SQL Query

```yaml
- step: query
  type: snowflake
  auth:
    sf:
      type: snowflake
      key: sf_test
  command: |
    SELECT * FROM my_table LIMIT 10;
```

### Use Template Variables

```yaml
workload:
  table_name: "users"
  limit: 100

workflow:
  - step: dynamic_query
    type: snowflake
    auth:
      sf:
        type: snowflake
        key: sf_test
    command: |
      SELECT * FROM {{ workload.table_name }}
      LIMIT {{ workload.limit }};
```

### Work with JSON Data

```yaml
- step: json_query
  type: snowflake
  auth:
    sf:
      type: snowflake
      key: sf_test
  command: |
    SELECT 
      id,
      data:name::STRING as name,
      data:tags as tags
    FROM json_table
    WHERE data:active = true;
```

### Multiple Statements

```yaml
- step: multi_statement
  type: snowflake
  auth:
    sf:
      type: snowflake
      key: sf_test
  command: |
    CREATE TEMP TABLE tmp AS SELECT 1 as id;
    INSERT INTO tmp VALUES (2);
    SELECT * FROM tmp;
```

## Troubleshooting

### Connection Issues

If you get connection errors:
1. Verify account identifier format (check `SETUP_GUIDE.md`)
2. Ensure warehouse is running
3. Check credentials are registered correctly
4. Test connection in Snowflake Web UI first

### Check NoETL Logs

```bash
# Worker logs
tail -f logs/worker-debug.log

# Server logs
tail -f logs/server-debug.log
```

### Verify Credentials

```bash
# List registered credentials
curl -s http://localhost:8083/api/auth/list | python3 -m json.tool
```

## Next Steps

1. Read `SETUP_GUIDE.md` for complete Snowflake account setup
2. Modify `snowflake_test.yaml` for your specific use case
3. Create your own playbooks using these as templates
4. Integrate Snowflake steps into larger data pipelines

## Support

- **Snowflake Docs**: https://docs.snowflake.com/
- **NoETL Docs**: ../../docs/
- **Python Connector**: https://docs.snowflake.com/en/user-guide/python-connector

## License

MIT License - See main NoETL LICENSE file
