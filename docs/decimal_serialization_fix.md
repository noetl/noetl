# Decimal Serialization Fix

## Problem

Executions using Snowflake queries with numeric aggregations (SUM, AVG, etc.) were getting stuck and never completing. The `execution_completed` event was never emitted.

### Root Cause

When Snowflake returns query results with `NUMERIC` or `DECIMAL` columns, the Python connector returns `decimal.Decimal` objects. When the worker tries to report events containing these results to the server via JSON, Python's default JSON encoder fails with:

```
Failed to report event: Object of type Decimal is not JSON serializable
```

This causes:
1. Worker executes the Snowflake query successfully ✅
2. Worker tries to emit `step_result` event → FAILS ❌
3. Worker tries to emit `action_completed` event → FAILS ❌
4. Worker marks job as `done` in queue ✅
5. Server never receives `action_completed`, so never transitions to next step
6. Execution stuck forever

### Example Failure

Execution: `238893843167051776`
- Step `verify_sf_data` with query: `SELECT SUM(amount) as total_amount FROM table`
- Queue status: `done`
- Event log: Missing `action_completed` for `verify_sf_data`
- Result: Execution stuck, never reached `cleanup` or `end` steps

## Solution

Added custom JSON serializer in `noetl/plugin/tool/reporting.py` that converts `Decimal` objects to `float` before serialization.

### Changes

```python
from decimal import Decimal
import json

def _decimal_serializer(obj):
    """Convert Decimal to float for JSON serialization."""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

def report_event(event_data: Dict[str, Any], server_url: str) -> Dict[str, Any]:
    # ...
    json_data = json.dumps(event_data, default=_decimal_serializer)
    response = client.post(url, content=json_data, headers={"Content-Type": "application/json"})
    # ...
```

### Testing

**Before Fix:**
- Execution: `238893843167051776`
- Status: STUCK at `verify_sf_data`
- Queue: `done`
- Events: Missing `action_completed`, no `execution_complete`

**After Fix:**
- Execution: `238896556424560640`
- Status: COMPLETED
- Queue: All jobs `done`
- Events: Complete event chain including `action_completed` for all steps and `execution_complete`

```sql
SELECT event_type, node_name, status 
FROM noetl.event 
WHERE execution_id = '238896556424560640' 
ORDER BY created_at DESC LIMIT 15;

     event_type     |     node_name     |  status   
--------------------+-------------------+-----------
 step_result        | cleanup           | COMPLETED
 execution_complete | end               | COMPLETED  ← Success!
 step_completed     | cleanup           | COMPLETED
 action_completed   | cleanup           | COMPLETED
 action_started     | cleanup           | STARTED
 step_result        | verify_sf_data    | COMPLETED
 step_started       | cleanup           | RUNNING
 step_completed     | verify_sf_data    | COMPLETED
 action_completed   | verify_sf_data    | COMPLETED  ← Now working!
```

## Impact

This fix resolves execution hanging for any playbook that:
- Uses Snowflake queries with numeric aggregations (SUM, AVG, COUNT, etc.)
- Transfers data containing NUMERIC/DECIMAL columns
- Returns Snowflake query results in events

## Related Issues

- Transfer action type implementation
- Snowflake plugin event reporting
- Worker event serialization

## Commit

```
commit c774bb7c
fix: handle Decimal type serialization in event reporting
```
