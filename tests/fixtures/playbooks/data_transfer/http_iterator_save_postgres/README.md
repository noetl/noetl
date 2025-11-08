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
5. **Validate Data**: Python validation to confirm expected records exist

## Key Features Tested

- **Iterator Type**: `tool: iterator` with sequential mode
- **Nested HTTP Task**: HTTP GET requests within iterator
- **Per-Item Save Block**: Save configuration on the HTTP task itself
- **Postgres Storage**: Save delegation to postgres with upsert mode
- **Jinja2 Templating**: Dynamic values using execution_id, city data, and result data
- **Data Validation**: Post-execution verification of saved records

## Running the Test

### Prerequisites

1. Local NoETL server running on port 8083
2. PostgreSQL accessible with `pg_local` credential registered
3. Python virtual environment activated

### Quick Run

```bash
# Complete test workflow (register + execute)
task test-http-iterator-save-full

# Or using full name
task test:local:http-iterator-save-full
```

### Step-by-Step

```bash
# 1. Register the playbook
task test-register-http-iterator-save

# 2. Execute the playbook
task test-execute-http-iterator-save
```

### Manual Execution

```bash
# Register
noetl register tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres.yaml \
  --host localhost --port 8083

# Execute
noetl execute playbook "tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres" \
  --host localhost --port 8083 --json
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
   - `iterator_started`
   - `iteration_started` (x3)
   - `save_started` (x3)
   - `save_completed` (x3)
   - `iteration_completed` (x3)
   - `iterator_completed`

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
- Iterator executor: `noetl/plugin/controller/iterator/executor.py`
- Iterator execution: `noetl/plugin/controller/iterator/execution.py`
- Save executor: `noetl/plugin/shared/storage/executor.py`

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

## References

- [Iterator Documentation](../../docs/simple/steps/iterator.md)
- [Save Block Documentation](../../docs/simple/steps/save.md)
- [Iterator Lifecycle Events](../../docs/ITERATOR_LIFECYCLE_EVENTS_IMPLEMENTATION.md)
- [Save Storage Test README](../../save_storage_test/README.md)
