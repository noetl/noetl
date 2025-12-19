# HTTP Iterator Save Postgres Test

## Overview

This test playbook validates the critical functionality of HTTP calls within an iterator with save blocks that persist data to PostgreSQL. This is a common pattern for data collection workflows.

## Problem Being Tested

**Issue**: Loops (iterators) with HTTP calls that have save blocks to Postgres don't save data and show no errors in events.

**Expected Behavior**: 
- Iterator executes HTTP calls for each item in collection
- Each HTTP response is saved to PostgreSQL via the save block
- Events show save_started, save_completed for each iteration
- Data appears in PostgreSQL table after execution

## Test Playbook

**Location**: `tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres.yaml`

**Path**: `tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres`

## Test Workflow

1. **Create Table**: Sets up `public.http_iterator_save_test` table
2. **Iterator with HTTP + Save**: 
   - Loops over 3 cities (London, Paris, Berlin)
   - Makes HTTP GET request to Open-Meteo weather API for each city
   - Saves each response to Postgres with upsert mode
3. **Verify Results**: Counts records and checks all cities have data
4. **Show Details**: Displays all saved records
5. **Validate Data**: Python validation receives data via `args:` in `next:` block

## Key Features Tested

- **Iterator Type**: `tool: iterator` with sequential mode
- **Nested HTTP Task**: HTTP GET requests within iterator
- **Per-Item Save Block**: Save configuration on the HTTP task itself
- **Postgres Storage**: Save delegation to postgres with upsert mode
- **Jinja2 Templating**: Dynamic values using execution_id, city data, and result data
- **Args-Based Data Passing**: Parameters passed via `args:` in `next:` block
- **Data Validation**: Post-execution verification with step result references

## Running the Test

### Prerequisites

1. Local NoETL server running on port 8083
2. PostgreSQL accessible with `pg_local` credential registered
3. Python virtual environment activated

### Quick Run

```bash
# Complete reset and execute workflow
task noetl:local:reset && sleep 2 && \
  task playbook:local:execute \
    PLAYBOOK=tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres \
    PORT=8083
```

### Step-by-Step

```bash
# 1. Start services (if not running)
task noetl:local:start

# 2. Re-register the playbook (if updated)
.venv/bin/noetl catalog register \
  tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres/http_iterator_save_postgres.yaml \
  --host localhost --port 8083

# 3. Execute the playbook
task playbook:local:execute \
  PLAYBOOK=tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres \
  PORT=8083
```

### Manual Execution

```bash
# Execute via CLI
.venv/bin/noetl execute playbook \
  tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres \
  --host localhost \
  --port 8083 \
  --payload '{"pg_auth": "pg_local"}' \
  --merge \
  --json
```

## Expected Results

### Success Criteria

1. **Table Created**: `public.http_iterator_save_test` exists
2. **Data Saved**: 3 records (one per city) inserted/upserted
3. **All Fields Populated**: Each record has:
   - `id`: `{execution_id}:{city_name}`
   - `execution_id`: Current execution ID
   - `city_name`: London, Paris, or Berlin
   - `temperature`: Numeric value from API
   - `latitude`, `longitude`: City coordinates
   - `http_status`: 200
   - `created_at`: Timestamp

4. **Events Generated**: 
   - `step_started`, `step_completed` for each workflow step
   - `action_started`, `action_completed` for each task execution
   - `iteration_started`, `iteration_completed` for each loop iteration
   - Save operations tracked in action events
   - `execution_completed` for successful workflow completion

5. **Validation Success**:
   - `validate_data` step completes with status: "success"
   - All validation checks return true
   - Message: "Validation passed: 3 records saved for 3 cities"

### Validation Query

```sql
SELECT 
  COUNT(*) as total_records,
  COUNT(DISTINCT city_name) as unique_cities,
  AVG(temperature) as avg_temperature
FROM public.http_iterator_save_test
WHERE execution_id = '<your_execution_id>';
```

Expected: `total_records=3, unique_cities=3`

### Check Validation Result

```sql
SELECT result 
FROM noetl.event 
WHERE execution_id = '<your_execution_id>' 
  AND node_id = 'validate_data' 
  AND event_type = 'step_result';
```

Expected output:
```json
{
  "status": "success",
  "validation": {
    "total_records_match": true,
    "unique_cities_match": true,
    "all_cities_saved": true
  },
  "counts": {
    "expected": 3,
    "actual_total": 3,
    "actual_unique": 3
  },
  "message": "Validation passed: 3 records saved for 3 cities"
}
```

## Troubleshooting

### No Data Saved

**Symptoms**: 
- Table is created but empty
- No save-related events in event log
- No errors reported

**Debug Steps**:

1. Check iterator execution logs:
```bash
# Look for iterator execution in worker logs
kubectl logs -n noetl deployment/noetl-worker --tail=200 | grep -i "iterator"
```

2. Check save execution logs:
```bash
# Look for save operations
kubectl logs -n noetl deployment/noetl-worker --tail=200 | grep -i "save"
```

3. Query events directly:
```sql
SELECT 
  event_type, 
  step_name, 
  status, 
  meta
FROM noetl.event
WHERE execution_id = '<your_execution_id>'
ORDER BY event_time;
```

4. Check for save block parsing:
```sql
SELECT 
  step_name,
  meta->>'save_config'
FROM noetl.event
WHERE execution_id = '<your_execution_id>'
  AND event_type = 'save_started';
```

### Events Missing

**Check**:
- Worker is receiving the execution request
- Iterator executor is being called
- Event callback is wired through the execution chain

**Code Locations**:
- Iterator executor: `noetl/tools/controller/iterator/executor.py`
- Iterator execution: `noetl/tools/controller/iterator/execution.py`
- Save executor: `noetl/tools/shared/storage/executor.py`

### HTTP Requests Failing

**Check**:
- Network connectivity to `api.open-meteo.com`
- HTTP response structure matches template expectations
- Rate limiting from weather API

## Related Tests

- `iterator_save_test.yaml` - Iterator with Python task and save
- `http_to_postgres_iterator.yaml` - HTTP to Postgres WITHOUT save blocks
- `http_to_databases.yaml` - HTTP with iterator to multiple databases
- `save_delegation_test.yaml` - Save storage delegation patterns

## Implementation Notes

### Save Block Location

The save block is attached to the **task** within the iterator, not the iterator step itself:

```yaml
- step: fetch_weather_data
  tool: iterator
  collection: "{{ workload.test_cities }}"
  element: city
  task:
    tool: http
    # ... http config ...
    save:              # <-- Save is on the task, not iterator
      storage: postgres
      # ... save config ...
```

This creates a **per-item save** where each iteration result is saved individually.

### Alternative: Step-Level Save

For aggregated results after all iterations:

```yaml
- step: fetch_weather_data
  tool: iterator
  # ... iterator config ...
  task:
    tool: http
    # ... http config ...
  save:                # <-- Save is on iterator step
    storage: postgres
    # ... save config for aggregated results ...
```

### Data Passing Between Steps

The playbook demonstrates passing data between steps using `args:` in the `next:` block:

```yaml
- step: show_details
  tool: postgres
  command: "SELECT * FROM table WHERE ..."
  next:
    - step: validate_data
      args:                              # Pass args to next step
        verify_results: "{{ verify_results }}"  # Reference previous step by name

- step: validate_data
  tool: python
  code: |
    def main(verify_results):          # Function parameter receives args
        # verify_results contains the result from verify_results step
        verify_result = verify_results.get('command_0')...
```

**Key Points**:
- Use `args:` in `next:` block to pass parameters to target steps
- Reference previous steps by name using Jinja2: `{{ step_name }}`
- The orchestrator automatically unwraps the `data` field from step results
- Python function parameters map to args keys via signature inspection
- No need to use `.data` suffix - orchestrator handles unwrapping

## References

- **Bug Fix Summary**: [HTTP_ITERATOR_SAVE_SUMMARY.md](./HTTP_ITERATOR_SAVE_SUMMARY.md)
- **Playbook DSL Spec**: [docs/dsl_spec.md](../../../../docs/dsl_spec.md)
- **Iterator Plugin**: [noetl/tools/controller/iterator/](../../../../noetl/tools/controller/iterator/)
- **Save Storage**: [noetl/tools/shared/storage/](../../../../noetl/tools/shared/storage/)
- **Data Passing**: Uses `args:` in `next:` block (planner.py)
