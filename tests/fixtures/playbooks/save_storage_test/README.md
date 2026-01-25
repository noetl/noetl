# Save Storage Test Playbooks

This directory contains comprehensive test playbooks for validating all save storage types in NoETL.

## Test Playbooks Overview

### 1. `save_all_storage_types.yaml`
**Purpose**: Comprehensive test covering all save storage types with data flow between steps

**Storage Types Tested**:
- `event_log` - Default event logging storage
- `postgres` (flat structure) - Basic postgres save with flat configuration
- `postgres` (nested structure) - Advanced postgres save with nested configuration and upsert
- `postgres` (custom SQL) - Postgres save with custom SQL statements
- `python` - Custom Python code execution for storage
- `duckdb` - Analytics queries and data processing
- `http` - Webhook/API calls for external storage

**Features**:
- Data flows from step to step demonstrating real workflow patterns
- Each step uses a different save storage type
- Comprehensive workbook tasks for data preparation
- Both flat and nested storage structure examples
- Custom SQL statements and upsert operations
- External API integration testing

**Usage**:
```bash
# Register the playbook
noetl playbook register tests/fixtures/playbooks/save_storage_test/save_all_storage_types.yaml

# Execute the test
noetl execution create tests/save_storage/all_types --data '{}'
```

### 2. `save_simple_test.yaml`
**Purpose**: Simple, focused test demonstrating basic save storage patterns

**Storage Types Tested**:
- `event_log` - Basic event storage
- `postgres` (flat) - Simple postgres insert
- `postgres` (nested) - Postgres with upsert using nested structure
- `python` - Basic Python storage with custom processing
- `duckdb` - Simple analytics table creation
- `http` - Basic webhook notification

**Features**:
- Minimal complexity for easy understanding
- Clear examples of each storage type
- Simple data transformations between steps
- Good starting point for learning save patterns

**Usage**:
```bash
# Register the playbook
noetl playbook register tests/fixtures/playbooks/save_storage_test/save_simple_test.yaml

# Execute the test
noetl execution create tests/save_storage/simple --data '{}'
```

### 3. `save_edge_cases.yaml`
**Purpose**: Test edge cases, error scenarios, and data handling robustness

**Test Scenarios**:
- **Mixed Data Types**: Testing strings, integers, floats, booleans, nulls, dates, lists, dicts
- **Special Characters**: Unicode, quotes, SQL injection prevention, newlines, backslashes
- **Empty Data**: Empty strings, lists, dicts, null values, zero values
- **Large Payloads**: Testing with moderately large datasets (100 records)
- **Error Recovery**: Testing error handling and graceful degradation

**Features**:
- Comprehensive data type coverage
- Security testing (SQL injection prevention)
- Unicode and internationalization support
- Large payload handling
- Error recovery patterns

**Usage**:
```bash
# Register the playbook
noetl playbook register tests/fixtures/playbooks/save_storage_test/save_edge_cases.yaml

# Execute the test
noetl execution create tests/save_storage/edge_cases --data '{}'
```

## Prerequisites

### Required Credentials
Before running these tests, ensure you have the following credentials registered:

```bash
# Postgres credential (already available in NoETL test environment)
# The tests use: auth: pg_k8s
# This should already be registered via: noetl run automation/test/register-test-credentials.yaml

# If you need to register manually:
noetl credential create pg_k8s --type postgres --data '{
  "host": "postgres.postgres.svc.cluster.local",
  "port": 5432,
  "user": "demo",
  "password": "demo",
  "database": "demo"
}'
```

### Required Database Tables
The postgres tests expect these tables to exist:

```sql
-- For comprehensive test
CREATE TABLE IF NOT EXISTS test_employees_flat (
    employee_id INTEGER PRIMARY KEY,
    name VARCHAR(255),
    department VARCHAR(255),
    salary INTEGER,
    storage_type VARCHAR(50),
    test_execution VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS test_employees_nested (
    employee_id INTEGER PRIMARY KEY,
    name VARCHAR(255),
    department VARCHAR(255),
    salary INTEGER,
    storage_type VARCHAR(50),
    test_execution VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS test_summary (
    id SERIAL PRIMARY KEY,
    summary_type VARCHAR(255),
    total_employees INTEGER,
    avg_salary DECIMAL(10,2),
    test_execution VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
);

-- For simple test
CREATE TABLE IF NOT EXISTS simple_test_flat (
    test_id VARCHAR(255) PRIMARY KEY,
    test_name VARCHAR(255),
    test_value DECIMAL(10,2),
    execution_id VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS simple_test_nested (
    test_id VARCHAR(255) PRIMARY KEY,
    test_name VARCHAR(255),
    test_value DECIMAL(10,2),
    execution_id VARCHAR(255),
    nested_indicator BOOLEAN
);

-- For edge cases
CREATE TABLE IF NOT EXISTS test_mixed_types (
    id SERIAL PRIMARY KEY,
    string_field TEXT,
    integer_field INTEGER,
    float_field DECIMAL(10,5),
    boolean_field BOOLEAN,
    null_field TEXT,
    datetime_field TIMESTAMP,
    list_field JSONB,
    dict_field JSONB,
    decimal_field DECIMAL(10,2)
);

CREATE TABLE IF NOT EXISTS test_special_chars (
    id SERIAL PRIMARY KEY,
    quotes TEXT,
    unicode TEXT,
    sql_injection TEXT,
    newlines TEXT,
    backslashes TEXT,
    json_string JSONB
);
```

## Test Execution Patterns

### Sequential Testing
Run all tests in sequence to validate complete save functionality:

```bash
# 1. Simple test first
noetl execution create tests/save_storage/simple --data '{}'

# 2. Comprehensive test
noetl execution create tests/save_storage/all_types --data '{}'

# 3. Edge cases
noetl execution create tests/save_storage/edge_cases --data '{}'
```

### Monitoring Test Results
Monitor test execution and results:

```bash
# Check execution status
noetl execution list --filter "playbook_path:tests/save_storage"

# View detailed logs
kubectl logs -n noetl deployment/noetl-worker --tail=100 | grep "save"

# Check saved data in postgres
psql -h localhost -U noetl_test -d noetl_test -c "SELECT * FROM test_employees_flat;"
```

## Expected Outcomes

### Success Criteria
- All steps complete successfully with `status: success`
- Data is properly saved to each storage type
- No template rendering errors
- Proper credential resolution and authentication
- Unicode and special characters handled correctly

### Validation Points
1. **Event Log**: All save operations logged to `noetl.event` table
2. **Postgres**: Data inserted/upserted correctly in target tables
3. **Python**: Custom code executes and returns expected results
4. **DuckDB**: Analytics queries run and return data
5. **HTTP**: Webhook calls succeed (200 response from httpbin.org)

## Troubleshooting

### Common Issues
1. **Missing Credentials**: Ensure `postgres_test` credential is registered
2. **Database Connection**: Verify postgres connection and table creation
3. **Template Errors**: Check Jinja2 template syntax in playbooks
4. **HTTP Timeouts**: External HTTP calls may timeout in restricted environments

### Debug Commands
```bash
# Check worker logs for save operations
kubectl logs -n noetl deployment/noetl-worker --follow | grep -E "(save|storage|postgres|python|duckdb|http)"

# Verify credential registration
noetl credential list

# Check execution events
noetl execution events <execution_id> --filter "action_type:save"
```

## Extension Points

These test playbooks can be extended for:
- Additional storage types (Redis, MongoDB, S3, etc.)
- Performance testing with larger datasets
- Concurrent save operations testing
- Custom authentication mechanisms
- Integration with external systems

The modular design allows easy addition of new test scenarios and storage types as the NoETL platform evolves.

## How to make sure these playbooks work correctly

Follow this quick checklist to ensure reliable runs on any environment (local Docker, K8s, or CI):

1) Pick the Postgres credential name used by the playbooks
- These playbooks reference a Postgres credential through `workload.pg_auth`.
- Some variants use `pg_local` (local/dev) while others may reference `pg_k8s` (cluster test env). Either:
  - Register a credential with that exact name, or
  - Edit the playbook's `workload.pg_auth` to match your existing credential name.

Examples to register credentials:
```bash
# Local Postgres (pg_local)
noetl credential create pg_local --type postgres --data '{
  "host": "localhost",
  "port": 5432,
  "user": "demo",
  "password": "demo",
  "database": "demo"
}'

# K8s Postgres (pg_k8s)
noetl credential create pg_k8s --type postgres --data '{
  "host": "postgres.postgres.svc.cluster.local",
  "port": 5432,
  "user": "demo",
  "password": "demo",
  "database": "demo"
}'
```

2) Ensure the NoETL services are running
- Local Docker Compose:
```bash
# From the project root
docker compose up -d postgres server worker
# Export the API URL if needed
export NOETL_SERVER_URL=http://localhost:8083
```
- Or ensure your K8s deployment is healthy and the CLI points to the correct server URL.

3) Create required database tables
You can do any one of the following:
- Run the bundled SQL manually (see the "Required Database Tables" section above) in your target Postgres.
- Use the helper shell script at project root:
```bash
./create_test_tables.sh  # creates required test tables in your configured Postgres
```
- Or run the table-creation playbook in this folder:
```bash
noetl playbook register tests/fixtures/playbooks/save_storage_test/create_tables.yaml
noetl execution create tests/save_storage/create_tables --data '{}'
```

4) Register the test playbooks
```bash
noetl playbook register tests/fixtures/playbooks/save_storage_test/save_simple_test.yaml
noetl playbook register tests/fixtures/playbooks/save_storage_test/save_all_storage_types.yaml
noetl playbook register tests/fixtures/playbooks/save_storage_test/save_edge_cases.yaml
```

5) Execute the tests
```bash
noetl execution create tests/save_storage/simple --data '{}'
noetl execution create tests/save_storage/all_types --data '{}'
noetl execution create tests/save_storage/edge_cases --data '{}'
```

6) Validate results automatically (recommended)
A convenience script validates that required rows were inserted and that basic invariants hold:
```bash
# From the project root
bash tests/fixtures/playbooks/save_storage_test/validate_tests.sh
```
- The script will:
  - Check server reachability
  - Confirm credential existence
  - Verify tables exist
  - Execute the playbooks (if not executed yet)
  - Query Postgres to verify rows were saved

7) Validate results manually (optional)
- Query your Postgres directly. Examples:
```bash
psql -h localhost -U demo -d demo -c "SELECT * FROM test_mixed_types LIMIT 5;"
psql -h localhost -U demo -d demo -c "SELECT * FROM test_special_chars LIMIT 5;"
psql -h localhost -U demo -d demo -c "SELECT * FROM simple_test_flat LIMIT 5;"
```
- Review events/logs:
```bash
# Worker logs (Docker)
docker logs noetl-worker 2>&1 | grep -i "save"
# Or K8s
kubectl logs -n noetl deployment/noetl-worker --tail=200 | grep -i "save"
```

Troubleshooting tips:
- Missing tables: ensure Step 3 completed (use the script or the create_tables playbook).
- Auth failures: verify the credential name in `workload.pg_auth` matches a registered credential.
- Connection issues: check `NOETL_SERVER_URL` and that `server` and `worker` containers/pods are running.
- Event visibility: if executions complete but you don't see failure events, ensure the `catalog_id` is set on queue jobs and propagated in events (register playbooks via the CLI so the server sets `catalog_id`).
