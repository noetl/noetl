# Multi-Playbook Batch Execution Example

This playbook demonstrates orchestrating multiple child playbooks in sequence, aggregating their results, and storing them in PostgreSQL using DuckDB.

## Overview

The workflow executes three different playbooks in sequence:
1. HTTP API test (httpbin.org)
2. Weather data processing with control flow
3. DuckDB GCS data transformation

Results from all three playbooks are collected and stored in a PostgreSQL table using DuckDB's postgres extension.

## Architecture

### Workflow Steps (7 total)

1. **start** - Initialize batch workflow (Python tool)
2. **run_http_test** - Execute HTTP API test playbook
3. **run_weather_processing** - Execute weather processing playbook with workbook control flow
4. **run_data_transformation** - Execute DuckDB GCS transformation playbook
5. **store_results** - Aggregate and store all results in PostgreSQL (Python tool with DuckDB)
6. **end** - Complete workflow (Python tool)

### Key Features

**Playbook Composition**: Uses `tool.kind: playbook` to orchestrate child playbooks:
```yaml
tool:
  kind: playbook
  path: tests/fixtures/playbooks/data_transfer/http_to_postgres_simple
  payload:
    url: https://httpbin.org/get
    method: GET
```

**Result Aggregation**: Collects outputs from all child playbooks and passes them to storage step:
```yaml
args:
  http_result: '{{ run_http_test }}'
  weather_result: '{{ run_weather_processing }}'
  data_result: '{{ run_data_transformation }}'
```

**DuckDB Postgres Integration**: Uses DuckDB's postgres extension to write results directly to PostgreSQL:
- Installs postgres and json extensions
- Attaches remote Postgres database
- Creates tables and inserts results in both DuckDB and Postgres
- Verifies successful insertion

**Python Tool Structure (v2)**: All python steps use standardized v2 format:
```yaml
tool:
  kind: python
  auth: {}
  libs:
    duckdb: duckdb
    json: json
    time: time
  args:
    execution_id: '{{ job.uuid }}'
  code: |
    # Direct code execution (no def main wrapper)
    result = {"status": "success"}
```

## Prerequisites

1. **NoETL Cluster Running**:
   - Kubernetes cluster with NoETL server and workers deployed
   - PostgreSQL database accessible

2. **Child Playbooks Registered**:
   ```bash
   noetlctl catalog register tests/fixtures/playbooks/data_transfer/http_to_postgres_simple/http_to_postgres_simple.yaml
   noetlctl catalog register tests/fixtures/playbooks/control_flow_workbook/control_flow_workbook.yaml
   noetlctl catalog register tests/fixtures/playbooks/duckdb_gcs_workload_identity/workload_identity.yaml
   ```

3. **PostgreSQL Connection**:
   - Host: `postgres.postgres.svc.cluster.local` (or configure in workload)
   - Database: `demo_noetl`
   - User/Password: `demo/demo`

4. **DuckDB Extensions**:
   - postgres extension (auto-installed in code)
   - json extension (auto-installed in code)

## Configuration

Update the `workload` section in `multi_playbook_batch.yaml`:

```yaml
workload:
  cities:
    - name: London
      lat: 51.51
      lon: -0.13
  base_url: https://api.open-meteo.com/v1
  temperature_threshold: 26
  baseFilePath: /opt/noetl/data/test
  bucket: test-bucket
  pg_host: postgres.postgres.svc.cluster.local
  pg_port: '5432'
  pg_user: demo
  pg_password: demo
  pg_db: demo_noetl
```

## Execution

### Using noetlctl (Recommended)

```bash
# Register the playbook
noetlctl catalog register tests/fixtures/playbooks/batch_execution/multi_playbook_batch/multi_playbook_batch.yaml

# Execute the playbook
noetlctl execute playbook batch_execution/multi_playbook_batch --json

# Get execution status (replace <EXECUTION_ID> with returned id)
noetlctl execute status <EXECUTION_ID> --json

# Alternative: Direct execution using path
noetlctl exec batch_execution/multi_playbook_batch
```

### Using REST API (Alternative)

```bash
# Execute via REST API
curl -X POST http://localhost:8082/api/run/playbook \
  -H "Content-Type: application/json" \
  -d '{"path": "batch_execution/multi_playbook_batch"}'

# Poll execution status
curl -s http://localhost:8082/api/executions/<EXECUTION_ID> | jq .
```

## Validating Results

### Check Execution Status

```bash
# Get execution details
noetlctl execute status <EXECUTION_ID> --json

# Check for completion
curl -s http://localhost:8082/api/executions/<EXECUTION_ID> | jq '.status'
```

### Query PostgreSQL Results Table

Using NoETL REST API for PostgreSQL queries:

```bash
# Get all batch results
curl -X POST http://localhost:8082/api/postgres/execute \
  -H "Content-Type: application/json" \
  -d '{
    "query": "SELECT * FROM playbook_batch_results ORDER BY timestamp DESC LIMIT 5",
    "connection_string": "postgresql://demo:demo@localhost:54321/demo_noetl"
  }' | jq .

# Get results for specific execution
curl -X POST http://localhost:8082/api/postgres/execute \
  -H "Content-Type: application/json" \
  -d '{
    "query": "SELECT execution_id, http_result, weather_result, data_result, timestamp FROM playbook_batch_results WHERE execution_id = '\''YOUR-EXECUTION-ID'\'' ORDER BY timestamp DESC",
    "connection_string": "postgresql://demo:demo@localhost:54321/demo_noetl"
  }' | jq .

# Count total records
curl -X POST http://localhost:8082/api/postgres/execute \
  -H "Content-Type: application/json" \
  -d '{
    "query": "SELECT COUNT(*) as total FROM playbook_batch_results",
    "connection_string": "postgresql://demo:demo@localhost:54321/demo_noetl"
  }' | jq .
```

### Using SQL Client (DBeaver, psql, etc.)

```sql
-- View all batch results
SELECT 
    id,
    execution_id,
    http_result::jsonb->>'status' as http_status,
    weather_result::jsonb->>'status' as weather_status,
    data_result::jsonb->>'status' as data_status,
    timestamp
FROM playbook_batch_results
ORDER BY timestamp DESC
LIMIT 10;

-- Get detailed results for specific execution
SELECT 
    execution_id,
    http_result::jsonb,
    weather_result::jsonb,
    data_result::jsonb,
    timestamp
FROM playbook_batch_results
WHERE execution_id = 'YOUR-EXECUTION-ID';

-- Verify data integrity
SELECT 
    COUNT(*) as total_records,
    COUNT(DISTINCT execution_id) as unique_executions,
    MIN(timestamp) as first_run,
    MAX(timestamp) as last_run
FROM playbook_batch_results;

-- Check for errors in child playbook results
SELECT 
    execution_id,
    timestamp,
    CASE 
        WHEN http_result::jsonb->>'status' != 'success' THEN 'HTTP Error'
        WHEN weather_result::jsonb->>'status' != 'success' THEN 'Weather Error'
        WHEN data_result::jsonb->>'status' != 'success' THEN 'Data Error'
        ELSE 'All Success'
    END as error_status
FROM playbook_batch_results
ORDER BY timestamp DESC;
```

### Check NoETL Event Log

```bash
# Query execution events via REST API
curl -X POST http://localhost:8082/api/postgres/execute \
  -H "Content-Type: application/json" \
  -d '{
    "query": "SELECT execution_id, node_name, status, error FROM noetl.event WHERE execution_id = YOUR_EXECUTION_ID ORDER BY created_at DESC",
    "schema": "noetl"
  }' | jq .
```

Or using SQL:

```sql
-- View execution flow
SELECT 
    id,
    node_name,
    status,
    data,
    error,
    created_at
FROM noetl.event
WHERE execution_id = YOUR_EXECUTION_ID
ORDER BY created_at ASC;

-- Check for failures
SELECT 
    node_name,
    status,
    error,
    created_at
FROM noetl.event
WHERE execution_id = YOUR_EXECUTION_ID
  AND status = 'failed'
ORDER BY created_at DESC;
```

### Verify Child Playbook Executions

```bash
# List all executions related to batch workflow
curl -s http://localhost:8082/api/executions | jq '.[] | select(.playbook_path | contains("batch_execution") or contains("http_to_postgres") or contains("control_flow") or contains("duckdb_gcs"))'
```

### Expected Output Structure

The `store_results` step should return:

```json
{
  "status": "success",
  "message": "Batch results stored successfully",
  "total_records": 2,
  "execution_id": "522107710393811426"
}
```

Each result field (http_result, weather_result, data_result) contains the output from the respective child playbook execution.

## Python Tool Pattern (v2)

This playbook demonstrates NoETL v2's standardized python tool structure:

### Structure
```yaml
tool:
  kind: python
  auth: {}      # Optional: authentication references
  libs:         # Required: library imports
    duckdb: duckdb
    json: json
    time: time
  args:         # Required: input arguments from workflow context
    execution_id: '{{ job.uuid }}'
    pg_host: '{{ workload.pg_host }}'
  code: |
    # Direct code execution - no def main() wrapper
    # Access inputs via variable names from args section
    conn = duckdb.connect()
    
    # Assign result to 'result' variable (not return statement)
    result = {
        "status": "success",
        "execution_id": execution_id
    }
```

### Key Principles
- **No Function Wrappers**: Code executes directly without `def main()` functions
- **Result Assignment**: Use `result = {...}` instead of `return {...}`
- **Library Imports**: Declare all imports in `libs` section
- **Input Arguments**: All inputs passed via `args` section, accessible as variables

### Example: store_results Step

```yaml
tool:
  kind: python
  libs:
    duckdb: duckdb
    json: json
    time: time
  args:
    http_result: '{{ run_http_test }}'
    weather_result: '{{ run_weather_processing }}'
    data_result: '{{ run_data_transformation }}'
    execution_id: '{{ job.uuid }}'
  code: |
    # Direct variable access from args
    http_json = json.dumps(http_result)
    
    # Create connection and process
    conn = duckdb.connect()
    conn.execute("CREATE TABLE IF NOT EXISTS results ...")
    
    # Assign result (not return)
    result = {
        "status": "success",
        "execution_id": execution_id
    }
```

## Error Handling

The workflow includes error handling at multiple levels:

### Child Playbook Failures
If any child playbook fails, the batch workflow will:
- Capture the error in the result variable
- Continue to the next step (depending on error handling configuration)
- Store the error status in the results table

### DuckDB/Postgres Errors
The `store_results` step includes try-catch error handling:
```python
try:
    # Database operations
    result = {"status": "success"}
except Exception as e:
    result = {
        "status": "error",
        "message": f"Failed to store batch results: {str(e)}"
    }
finally:
    conn.close()
```

### Monitor Execution Errors

```sql
-- Check for batch workflow errors
SELECT 
    execution_id,
    node_name,
    status,
    error,
    created_at
FROM noetl.event
WHERE playbook_name = 'multi_playbook_batch'
  AND status = 'failed'
ORDER BY created_at DESC;
```

## Troubleshooting

### Child Playbook Not Found
Ensure all child playbooks are registered:
```bash
noetlctl catalog list Playbook | grep -E "(http_to_postgres|control_flow|duckdb_gcs)"
```

### Database Connection Failed
Verify PostgreSQL accessibility:
```bash
# Test connection via NoETL REST API
curl -X POST http://localhost:8082/api/postgres/execute \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT 1", "connection_string": "postgresql://demo:demo@localhost:54321/demo_noetl"}' | jq .
```

### DuckDB Extension Errors
DuckDB extensions are installed automatically in the code. If errors occur:
- Check DuckDB version compatibility
- Verify postgres extension availability
- Review execution logs for installation errors

### Python Tool Errors
Verify python tools follow v2 structure:
```yaml
# ❌ Bad (v1 style with def main)
code: |
  def main(arg1, arg2):
      return {"result": arg1}

# ✅ Good (v2 style)
tool:
  kind: python
  libs: {}
  args:
    arg1: '{{ step.data }}'
    arg2: '{{ workload.value }}'
  code: |
    result = {"result": arg1}
```

### Results Table Not Created
Check table creation permissions:
```sql
-- Verify table exists
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
  AND table_name = 'playbook_batch_results';

-- Check table schema
\d playbook_batch_results
```

## Use Cases

This batch execution pattern is useful for:

1. **Data Pipeline Orchestration**: Sequential execution of ETL jobs with dependency management
2. **Integration Testing**: Running multiple test scenarios and aggregating results
3. **Multi-Source Data Collection**: Gathering data from different sources and consolidating
4. **Workflow Composition**: Building complex workflows from reusable playbook components
5. **Result Aggregation**: Collecting and storing outputs from multiple operations

## References

- [NoETL Playbook Composition](../../../../documentation/docs/features/playbook-composition.md)
- [NoETL DSL Specification](../../../../documentation/docs/reference/dsl-spec.md)
- [DuckDB Postgres Extension](https://duckdb.org/docs/extensions/postgres.html)
- [Python Tool Pattern v2](../../../postgres_excel_gcs_test/README.md#python-tool-pattern-v2)
