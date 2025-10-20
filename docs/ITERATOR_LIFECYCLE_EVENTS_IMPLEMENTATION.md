# Iterator Lifecycle Events Implementation

## Overview

This document describes the implementation of explicit lifecycle event reporting for iterator/loop execution in NoETL. The goal is to provide clear visibility into execution flow with explicit events for:

- `iterator_started` - When iterator begins processing
- `iteration_started` - When each iteration begins  
- `iteration_completed` - When each iteration succeeds
- `iteration_failed` - When an iteration fails
- `save_started` - When a per-item save operation begins
- `save_completed` - When a save operation succeeds
- `save_failed` - When a save operation fails with known error
- `save_error` - When a save operation fails with unexpected error

## Problem Statement

Previously, the iterator execution flow lacked explicit lifecycle event reporting. This made it difficult to:

1. **Track execution progress** - No visibility into which iterations were running
2. **Debug failures** - Save failures were silent or unclear
3. **Monitor performance** - No metrics on per-iteration timing
4. **Implement transaction semantics** - Save failures didn't properly propagate to fail the entire action

## Implementation Changes

### File: `noetl/plugin/iterator/execution.py`

#### 1. Updated `execute_per_item_save()` function

**Added Parameters:**
- `log_event_callback: Optional[Callable]` - Callback for event reporting  
- `iter_index: int` - Current iteration index for event identification

**Event Reporting:**
```python
# Emit save_started event before executing save
if log_event_callback:
    log_event_callback(
        'save_started', None, f'save_iter_{iter_index}', 'save',
        'in_progress', 0, iter_ctx, None,
        {'iteration_index': iter_index, 'save_config': nested_save},
        None
    )

# After save execution:
# - Emit save_completed on success
# - Emit save_failed on known error
# - Emit save_error on unexpected exception
```

**Transaction Semantics:**
- Save failures raise exceptions immediately
- Exceptions propagate to fail the entire iteration
- No silent failures - all errors are explicit

#### 2. Updated `run_one_iteration()` function

**Added Parameter:**
- `log_event_callback: Optional[Callable]` - Callback for event reporting

**Event Reporting:**
```python
# At iteration start
if log_event_callback:
    log_event_callback(
        'iteration_started', None, f'iter_{iter_index}', 'iteration',
        'in_progress', 0, context, None,
        {'iteration_index': iter_index, 'has_save': bool(nested_task.get('save'))},
        None
    )

# On nested task failure:
log_event_callback('iteration_failed', ...)

# On save failure:
log_event_callback('iteration_failed', ...)  # Save failure fails the iteration

# On success:
log_event_callback('iteration_completed', ...)
```

**Call Chain:**
- Passes `log_event_callback` and `iter_index` to `execute_per_item_save()`
- Ensures save events are properly reported within iteration context

### File: `noetl/plugin/iterator/executor.py`

#### 1. Added `iterator_started` event

**At Start of `execute_loop_task()`:**
```python
# Emit explicit iterator_started event
if log_event_callback:
    log_event_callback(
        'iterator_started', task_id, task_name, 'iterator',
        'in_progress', 0, context, None,
        {'task_config': task_config},
        None
    )
```

#### 2. Updated iteration execution calls

**Sequential Mode:**
```python
rec = run_one_iteration(
    idx, payload, context, task_config, config, jinja_env, log_event_callback
)
```

**Async Mode:**
```python
pool.submit(
    run_one_iteration, idx, payload, context, 
    task_config, config, jinja_env, log_event_callback
)
```

## Event Flow Diagram

```
execution_start
    ↓
step_started (http_loop)
    ↓
action_started (http_loop)
    ↓
iterator_started
    ↓
┌─────────────────────────────────────┐
│ FOR EACH ITERATION:                 │
│   iteration_started                 │
│       ↓                              │
│   [execute nested task]             │
│       ↓                              │
│   save_started (if save configured) │
│       ↓                              │
│   [execute save]                    │
│       ↓                              │
│   save_completed/failed             │
│       ↓                              │
│   iteration_completed/failed        │
└─────────────────────────────────────┘
    ↓
action_completed (http_loop)
    ↓
step_completed (http_loop)
```

## Testing

### Test Playbook

The implementation was tested with:
`tests/fixtures/playbooks/http_duckdb_postgres/http_duckdb_postgres.yaml`

**Key Features:**
- Iterator with 3 cities (London, Paris, Berlin)
- HTTP API calls per city
- Per-item save to PostgreSQL with upsert mode
- DuckDB aggregation step

**Execution Command:**
```bash
.venv/bin/noetl execute playbook "tests/fixtures/playbooks/http_duckdb_postgres" \
  --host localhost --port 8083 \
  --payload '{"pg_auth": "pg_local"}' \
  --merge
```

### Expected Events

For the test playbook with 3 cities, the expected event sequence is:

```
1. iterator_started (http_loop)
2. iteration_started (iter_0 - London)
3. save_started (save_iter_0)
4. save_completed (save_iter_0)
5. iteration_completed (iter_0)
6. iteration_started (iter_1 - Paris)
7. save_started (save_iter_1)
8. save_completed (save_iter_1)
9. iteration_completed (iter_1)
10. iteration_started (iter_2 - Berlin)
11. save_started (save_iter_2)
12. save_completed (save_iter_2)
13. iteration_completed (iter_2)
```

## Known Issues

### 1. Save Block Not Executing

**Status:** ❌ **CRITICAL BUG**

**Symptoms:**
- Execution completes with status `COMPLETED`
- No data is written to PostgreSQL table
- No `save_started`, `save_completed`, or `save_failed` events appear in logs
- `weather_pipeline_metrics` table shows `pg_rows_saved = 0`

**Evidence:**
```sql
SELECT * FROM public.weather_pipeline_metrics WHERE execution_id = '237088202131767296';
-- Result: pg_rows_saved = 0
```

**Root Cause:** Unknown - needs investigation. Possible causes:
1. Save block is being skipped during iteration execution
2. Save configuration not being properly extracted from nested task
3. Event callback not being properly wired through execution chain
4. Worker not executing the iterator task at all (running server-side instead?)

### 2. Event Callback Not Wired Through Worker

**Status:** ⚠️ **NEEDS VERIFICATION**

The `log_event_callback` parameter added to iterator functions needs to be properly wired from:
1. Worker's job execution (`noetl/worker/worker.py`)
2. Plugin executor (`noetl/plugin/base.py` or similar)
3. Iterator executor (`noetl/plugin/iterator/executor.py`)

**Current State:** Callback parameter added to functions but may not be receiving actual callback from worker.

### 3. Missing Event Persistence

**Status:** ⚠️ **TO BE VERIFIED**

Need to confirm that the new event types are:
1. Properly sent to server via `report_event()`
2. Persisted to database
3. Triggering appropriate broker evaluations
4. Visible in execution timeline/logs

## Next Steps

### Immediate Priority

1. **Debug save execution flow:**
   ```python
   # Add debug logging in noetl/plugin/iterator/execution.py
   logger.critical(f"ITERATOR: Has save block: {nested_task.get('save')}")
   logger.critical(f"ITERATOR: Save config: {nested_save}")
   logger.critical(f"ITERATOR: Calling execute_save_task")
   ```

2. **Verify event callback wiring:**
   - Check if `log_event_callback` is None in iterator execution
   - Trace callback from worker through plugin executor to iterator

3. **Check if iterator is executing at all:**
   - Verify http_loop step is actually executing iterations
   - Check worker logs for iterator execution messages
   - Confirm nested task results are being generated

### Medium Priority

4. **Event schema validation:**
   - Ensure new event types are recognized by server
   - Verify event persistence and retrieval
   - Check event timeline display

5. **Integration testing:**
   - Create dedicated test for lifecycle events
   - Verify event counts and sequence
   - Test error scenarios (save failures, iteration failures)

6. **Documentation:**
   - Update playbook specification with event details
   - Add event monitoring guide
   - Document troubleshooting procedures

### Long Term

7. **Performance monitoring:**
   - Add timing metrics to events
   - Track iteration throughput
   - Monitor save performance

8. **Error handling improvements:**
   - Implement retry logic for save failures
   - Add circuit breaker for repeated failures
   - Improve error messages and context

## Summary

**What Was Implemented:**
✅ Explicit lifecycle event definitions for iterator/save operations
✅ Event reporting calls added throughout execution flow
✅ Transaction semantics for save failures (raise exceptions)
✅ Event callback parameter threading through function chain
✅ Comprehensive logging for debugging

**What Needs Investigation:**
❌ Why save blocks are not executing
❌ Why no events are being emitted
❌ How to properly wire event callback from worker
❌ Whether iterator is executing iterations at all

**Impact:**
- Better observability (when working)
- Clear failure propagation
- Foundation for monitoring and alerting
- Easier debugging of execution flow

## References

- Iterator Executor: `noetl/plugin/iterator/executor.py`
- Iterator Execution: `noetl/plugin/iterator/execution.py`
- Save Plugin: `noetl/plugin/save/executor.py`
- Worker: `noetl/worker/worker.py`
- Event Reporting: `noetl/plugin/tool/reporting.py`
