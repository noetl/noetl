# HTTP Iterator Save Test - Summary

## Overview

This test validates the HTTP iterator with per-item save pattern - a critical workflow combining iterator loops with HTTP requests and PostgreSQL persistence.

**Status**: ✅ **FIXED** - All issues resolved as of 2025-11-08

## Bugs Fixed

### 1. **Critical: Unreachable Save Code**
**File**: `noetl/tools/controller/iterator/execution.py` (lines 268-336)

**Problem**: Save execution code had incorrect indentation (8 spaces instead of 4), making it part of an `except Exception: pass` block and therefore unreachable.

```python
# BEFORE - Save code was NEVER executed
try:
    ctx_for_save["this"] = nested_result
except Exception:
    pass
        # These lines had 8-space indentation - unreachable!
        from noetl.tools.shared.storage import execute_save_task
        save_result = _do_save(...)
```

**Fix**: Removed the silent exception handler and fixed indentation:
```python
# AFTER - Save code properly executes
ctx_for_save["this"] = nested_result
if isinstance(nested_result, dict):
    ctx_for_save["result"] = nested_result

try:
    from noetl.tools.shared.storage import execute_save_task
    save_result = _do_save(...)
except Exception as e:
    raise  # Proper error propagation
```

**Impact**: Iterator save operations now execute correctly with 3/3 records saved.

### 2. **DateTime Serialization Error**
**File**: `noetl/tools/tools/postgres/execution.py` (function `_fetch_result_rows`)

**Problem**: PostgreSQL queries returning datetime/date/time objects caused JSON serialization errors.

**Fix**: Added datetime handling:
```python
from datetime import datetime, date, time

# In _fetch_result_rows:
elif isinstance(value, (datetime, date, time)):
    row_dict[col_name] = value.isoformat()
```

**Impact**: PostgreSQL results with timestamps now serialize correctly.

### 3. **Silent Exception Swallowing**
**Problem**: `except Exception: pass` anti-pattern hid errors in context setup.

**Fix**: Removed unnecessary try-except wrapper - let errors propagate naturally.

### 4. **Data Passing via Args in Next Block**
**File**: `noetl/server/api/run/planner.py` (lines 142, 156-160)

**Problem**: NoETL planner only recognized `data:` or `with:` in the `next:` block for passing arguments, but not `args:`.

**Fix**: Updated planner to recognize `args:` as the primary parameter passing mechanism:
```python
# Line 142 - Added args as first option
with_params = next_item.get("args") or next_item.get("data") or next_item.get("with") or {}

# Lines 156-160 - Also for conditional then blocks
"with_params": then_item.get("args")
               or then_item.get("data")
               or then_item.get("with")
               or {},
```

**Usage in Playbook**: Parameters passed via `args:` in `next:` block:
```yaml
- step: show_details
  tool: postgres
  command: "SELECT * FROM ..."
  next:
    - step: validate_data
      args:                              # Pass args to next step
        verify_results: "{{ verify_results }}"  # Reference previous step by name

- step: validate_data
  tool: python
  code: |
    def main(verify_results):          # Function parameter receives args
        verify_result = verify_results.get('command_0')...
```

**Key Points**:
- Use `args:` in the `next:` block to pass data to target steps
- Reference previous step results by step name (e.g., `{{ verify_results }}`)
- The orchestrator unwraps the `data` field from step results automatically
- Function parameters map directly to args keys via signature inspection

## Created Files

### 1. Test Playbook
**File**: `tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres/http_iterator_save_postgres.yaml`

Complete test playbook that:
- Creates PostgreSQL table for test data
- Executes iterator over 3 cities (London, Paris, Berlin)
- Makes HTTP GET requests to Open-Meteo weather API
- Saves each response to Postgres with per-item save block
- Verifies record counts and validates all data was saved correctly

### 2. Documentation
**File**: `tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres/README.md`

Complete documentation with problem description, workflow, and troubleshooting.

## Running the Test

### Recommended Method
```bash
# Register and execute playbook
noetl playbook register tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres

noetl execution create tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres
```

### Manual Execution
```bash
# 1. Start services (if not running)
noetl run automation/setup/bootstrap.yaml

# 2. Execute playbook using CLI with custom options
noetl execute playbook \
  tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres \
  --host localhost \
  --port 8083 \
  --payload '{"pg_auth": "pg_local"}' \
  --merge \
  --json
```

### Verification Only
```bash
# Verify results from previous execution
PGPASSWORD=demo psql -h localhost -p 54321 -U demo -d demo_noetl \
  -c "SELECT city_name, temperature FROM public.http_iterator_save_test ORDER BY city_name;"
```

## Execution Results

### Successful Test Run (2025-11-08)

**Execution ID**: `490869469632266329`

**Database Results**:
```
 city_name | temperature | latitude | longitude
-----------+-------------+----------+-----------
 Berlin    |         3.9 |    52.52 |    13.405
 London    |        13.0 |  51.5074 |   -0.1278
 Paris     |        10.6 |  48.8566 |    2.3522
(3 rows)
```

**Validation Results**:
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
  },
  "counts": {
    "expected": 3,
    "actual_total": 3,
    "actual_unique": 3
  },
  "message": "Validation passed: 3 records saved for 3 cities"
}
```

**Event Status**:
```
event_type           | node_id        | status
---------------------+----------------+-----------
execution_completed  | playbook       | COMPLETED
workflow_completed   | workflow       | COMPLETED
action_completed     | validate_data  | COMPLETED
action_completed     | show_details   | COMPLETED
action_completed     | verify_results | COMPLETED
action_completed     | fetch_weather_data | COMPLETED
action_completed     | create_table   | COMPLETED
```

**Worker Logs** (Save Execution):
```
ITERATOR.SAVE: execute_per_item_save called for iter_index=0
SAVE.EXECUTOR: execute_save_task CALLED
SAVE.EXECUTOR: Delegating to postgres handler with table=public.http_iterator_save_test
ITERATOR.SAVE: execute_save_task returned: {'status': 'success', 'row_count': 1}
```

## Test Structure

## What This Tests

This test specifically validates the critical pattern:
- **Iterator** with HTTP calls
- **Save block** on the HTTP task (per-item save)
- **Postgres storage** delegation
- **Event generation** for save operations
- **DateTime serialization** in PostgreSQL results
- **Python validation** with proper data passing

This addresses the original issue: "Loop with HTTP calls doesn't save data in postgres and no errors in the events."

## Key Playbook Pattern

```yaml
- step: fetch_weather_data
  tool: iterator
  collection: "{{ workload.test_cities }}"  # [London, Paris, Berlin]
  element: city
  mode: sequential
  task:
    tool: http
    method: GET
    url: "https://api.open-meteo.com/v1/forecast"
    params:
      latitude: "{{ city.lat }}"
      longitude: "{{ city.lon }}"
      current: temperature_2m
    save:                    # <-- Per-item save block
      storage: postgres
      auth: "{{ workload.pg_auth }}"
      table: public.http_iterator_save_test
      mode: upsert
      key: id
      args:
        id: "{{ execution_id }}:{{ city.name }}"
        city_name: "{{ city.name }}"
        temperature: "{{ result.data.data.current.temperature_2m }}"
        latitude: "{{ city.lat }}"
        longitude: "{{ city.lon }}"
        http_status: 200
```

**Critical Template Path**: `result.data.data.current.temperature_2m`
- `result` = HTTP task result context
- `.data` = HTTP response wrapper
- `.data` = actual API response body
- `.current.temperature_2m` = weather data field

## Expected Behavior (After Fix)

✅ **Working correctly**:
1. ✅ 3 HTTP requests made (one per city)
2. ✅ 3 save operations executed (logs show save_task calls)
3. ✅ 3 records in PostgreSQL table with actual temperature data
4. ✅ Events: save_started, save_completed for each iteration
- ✅ Validation step confirms all data present
- ✅ DateTime values serialized as ISO format strings
- ✅ Python validation receives data correctly via args in next block
- ✅ Data flow works: verify_results → args → validate_data

## Verification Queries

## Verification Queries

### Check Saved Data
```bash
psql -h localhost -p 54321 -U demo -d demo_noetl -c \
  "SELECT city_name, temperature, latitude, longitude, created_at
   FROM public.http_iterator_save_test
   ORDER BY city_name;"
```

### Check Execution Events
```bash
psql -h localhost -p 54321 -U demo -d demo_noetl -c \
  "SELECT event_type, node_id, status, error
   FROM noetl.event
   WHERE execution_id = '<execution_id>'
   ORDER BY event_id DESC
   LIMIT 20;"
```

### Check Validation Results
```bash
psql -h localhost -p 54321 -U demo -d demo_noetl -c \
  "SELECT result
   FROM noetl.event
   WHERE execution_id = '<execution_id>'
     AND node_id = 'validate_data'
     AND event_type = 'action_completed';"
```

### Check Worker Logs for Save Execution
```bash
grep "SAVE.EXECUTOR\|ITERATOR.SAVE" logs/worker.log | tail -20
```

## Technical Details

### Root Cause Analysis

The bug existed in the iterator's save execution path:

1. **Context Setup**: Lines 269-278 prepared the save context with result data
2. **Silent Failure**: Lines 279-280 wrapped context setup in `try/except: pass`
3. **Indentation Bug**: Lines 281-336 had 8-space indentation instead of 4
4. **Result**: Save code became part of the except block and was NEVER executed

The iterator would:
- ✅ Execute HTTP requests successfully
- ✅ Return results to the iterator loop
- ✅ Report "errors=0" because no exceptions occurred
- ❌ Skip all save operations silently
- ❌ Leave database empty with no error messages

### Why This Was Hard to Debug

1. **No Error Messages**: Silent `except: pass` swallowed any potential errors
2. **Success Reported**: Iterator reported "Completed with 3 results (errors=0)"
3. **HTTP Works**: The HTTP requests executed correctly, masking the save issue
4. **Template Rendering**: Templates showed in logs but were never actually used
5. **Event Logs Clean**: No save_started or save_completed events, but no failures either

### The Fix Chain

Multiple issues needed fixing in sequence:

1. **HTTP Params Bug** (first discovery): Empty dict `{}` didn't trigger params fallback
   - Fixed: Changed `if params is None` to `if (not params)`

2. **Template Path Bug**: Wrong result access path
   - Fixed: `result.data.current` → `result.data.data.current.temperature_2m`

3. **Indentation Bug** (critical): Save code unreachable
   - Fixed: Corrected indentation from 8 spaces to 4 spaces

4. **Exception Swallowing**: Silent error hiding
   - Fixed: Removed `except Exception: pass` anti-pattern

5. **DateTime Serialization**: JSON serialization error
   - Fixed: Added `isinstance(value, (datetime, date, time))` check with `.isoformat()`

6. **Data Passing Pattern**: Args not recognized in next block
   - Fixed: Updated planner to check `args` first, before `data` or `with`

7. **Template Reference**: Using `.data` when already unwrapped
   - Fixed: Changed `{{ verify_results.data }}` to `{{ verify_results }}`

## Comparison with Existing Tests

This test differs from other iterator tests in the codebase:

## Comparison with Existing Tests

This test differs from other iterator tests in the codebase:

- **`iterator_save_test.yaml`**: Uses Python task, not HTTP - different code path
- **`http_to_postgres_iterator.yaml`**: Uses Postgres INSERT in iterator, no save block
- **`http_to_databases.yaml`**: Uses workbook reference, not inline HTTP with save

**This is the ONLY test that combines**:
- ✅ Iterator tool
- ✅ HTTP tool (inline, not workbook)
- ✅ Save block (per-item)
- ✅ Postgres storage
- ✅ Template-based data extraction
- ✅ Python validation step

Perfect for catching iterator + HTTP + save integration bugs!

## Files Modified

### Core Fixes
1. **`noetl/tools/controller/iterator/execution.py`**
   - Fixed indentation bug (lines 268-336)
   - Removed `except Exception: pass` anti-pattern
   - Proper error propagation

2. **`noetl/tools/tools/postgres/execution.py`**
   - Added datetime/date/time serialization
   - Import `from datetime import datetime, date, time`
   - Convert to ISO format strings

3. **`noetl/server/api/run/planner.py`**
   - Added `args:` support in next block (line 142)
   - Added `args:` support in conditional then blocks (lines 156-160)
   - Priority order: args → data → with

4. **`noetl/tools/tools/http/request.py`** (earlier fix)
   - Fixed empty dict params fallback

5. **`noetl/tools/tools/http/executor.py`** (earlier fix)
   - Fixed exception handling in URL validation

### Test Files
1. **`tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres/http_iterator_save_postgres.yaml`**
   - Complete test playbook
   - Uses args in next block to pass data between steps
   - Python validation with signature-based parameter mapping

2. **`tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres/HTTP_ITERATOR_SAVE_SUMMARY.md`** (this file)
   - Test documentation and bug analysis

3. **`tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres/README.md`**
   - Detailed usage documentation

### Documentation Updates
1. **`docs/plugins/http.md`** (earlier update)
   - Merged documentation
   - Fixed YAML examples (`type:` → `tool:`)

## Lessons Learned

### Code Quality Rules Applied

1. **Never use `except Exception: pass`**
   - Always raise or log exceptions
   - Silent failures hide critical bugs
   - Use explicit validation instead

2. **Indentation Matters**
   - Python indentation creates code structure
   - 4-space indentation is standard
   - Misalignment can make code unreachable

4. **Type Handling for Serialization**
   - Always handle datetime/decimal types for JSON
   - Use `.isoformat()` for datetime objects
   - Check types before serialization

5. **Data Passing Patterns**
   - Use `args:` in `next:` block for passing parameters to target steps
   - Reference previous step results by step name: `{{ step_name }}`
   - Orchestrator automatically unwraps `data` field from step results
   - Python function parameters map to args keys via signature inspection

6. **Template Path Validation**
   - Verify template paths match actual data structure
   - Use logging to inspect runtime values
   - Document expected data shapes
   - Remember orchestrator unwrapping: `{{ step.data }}` may already be `{{ step }}`

## Success Criteria

All criteria now met:

- ✅ Iterator executes 3 times (one per city)
- ✅ HTTP GET requests return weather data
- ✅ Save operations execute for each iteration
- ✅ 3 records persisted to PostgreSQL
- ✅ Temperature values are actual API data (not null/0)
- ✅ DateTime values serialized correctly
- ✅ Validation step passes all checks
- ✅ No errors in event log
- ✅ Worker logs show save execution
- ✅ Execution status: COMPLETED

**Test demonstrates**: HTTP iterator with per-item save works correctly end-to-end.
