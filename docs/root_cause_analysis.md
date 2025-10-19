# Root Cause Analysis: Task Enqueueing Failure

**Date:** October 17, 2025  
**Status:** 🔍 ROOT CAUSE IDENTIFIED

## Executive Summary

Executions fail because **TWO PARALLEL BROKER SYSTEMS** exist, and the WRONG one is being used:

1. **OLD System** (`noetl/server/api/event/processing/broker.py`): Emits `step_started` but doesn't enqueue tasks properly
2. **NEW System** (`noetl/server/api/event/service/`): Properly dispatches and enqueues tasks - BUT IS NEVER CALLED

## The Smoking Gun

### Events Created Successfully
```sql
SELECT event_type, node_name FROM noetl.event WHERE execution_id = 237770008610996224;
   event_type    |       node_name       
-----------------+-----------------------
 execution_start | control_flow_workbook
 step_started    | eval_flag  -- ✅ Created!
```

### Queue Entry Missing
```sql
SELECT * FROM noetl.queue WHERE execution_id = 237770008610996224;
(0 rows)  -- ❌ NOT CREATED!
```

### Debug Logs Silent
```bash
$ tail -100 logs/server.log | grep -E "INITIAL|QUEUE|BROKER"
(no output)  -- ❌ NEW service layer never executed!
```

## Code Flow Analysis

### What SHOULD Happen (NEW System)
1. Event created → `POST /events`
2. Triggers `evaluate_execution()` from `noetl/server/api/event/service/core.py`
3. Calls `dispatch_first_step()` from `initial.py`
4. Emits `step_started` event
5. Calls `enqueue_task()` to insert into queue
6. Worker picks up job and executes

### What IS Happening (Current State)
1. Event created → `POST /events`
2. **UNKNOWN SYSTEM** emits `step_started` directly
3. No `dispatch_first_step()` called (no INITIAL logs)
4. No `enqueue_task()` called (no QUEUE logs)
5. Worker never receives job
6. Execution hangs

## Evidence

### File: `noetl/server/api/event/events.py` (Lines 209-222)

**Current Code:**
```python
# Trigger orchestration evaluation for this execution
try:
    execution_id = result.get("execution_id") or body.get("execution_id")
    if execution_id:
        logger.info(f"EVENTS: About to trigger evaluate_execution for {execution_id}")
        try:
            import asyncio
            task = asyncio.create_task(evaluate_execution(execution_id))
            logger.info(f"EVENTS: Created asyncio task for evaluate_execution: {task}")
        except Exception as eval_error:
            logger.error(f"EVENTS: Failed to create evaluate_execution task: {eval_error}", exc_info=True)
            pass  # Orchestration will be triggered by event emission
except Exception as outer_error:
    logger.error(f"EVENTS: Outer exception in orchestration trigger: {outer_error}", exc_info=True)
    pass
```

**Problem:** The log "EVENTS: About to trigger evaluate_execution" NEVER APPEARS in logs!

This means either:
1. `result` doesn't contain `execution_id`
2. `body` doesn't contain `execution_id`  
3. This code block is never reached
4. Exception is thrown before logging

### Parallel Broker Systems

**OLD Broker** (`noetl/server/api/event/processing/broker.py`):
```python
async def evaluate_broker_for_execution(execution_id: str):
    # ... Complex logic that emits step_started directly ...
    # ... BUT doesn't properly enqueue tasks ...
```

**NEW Broker** (`noetl/server/api/event/service/core.py`):
```python
async def evaluate_execution(execution_id: str):
    # Determines state and calls:
    # - dispatch_first_step() for initial
    # - process_completed_steps() for transitions
    # ... Properly enqueues tasks ...
```

### Where step_started is Emitted

**Multiple locations found:**
1. ✅ `noetl/server/api/event/service/initial.py:127` - NEW system (with logs)
2. ✅ `noetl/server/api/event/service/transitions.py:163` - NEW system (with logs)
3. ❌ `noetl/server/api/event/processing/broker.py:368` - OLD system (direct emission)
4. ❌ `noetl/server/api/event/processing/broker.py:419` - OLD system (direct emission)

Since our logs from #1 and #2 don't appear, but step_started IS created, **the OLD broker (#3/#4) must be running**.

## Root Cause

**The NEW service layer `evaluate_execution()` is NEVER BEING CALLED.**

Possible reasons:
1. Import failure silently caught
2. `execution_id` not in result/body
3. Code path never reached
4. Different event routing mechanism in use

## Next Steps

### Immediate Action: Add Aggressive Logging

```python
# At TOP of create_event function (line ~18)
logger.info(f"===== CREATE_EVENT CALLED =====")

# Before orchestration trigger (line ~208)
logger.info(f"===== ORCHESTRATION TRIGGER START =====")
logger.info(f"result keys: {list(result.keys()) if isinstance(result, dict) else 'NOT A DICT'}")
logger.info(f"body keys: {list(body.keys()) if isinstance(body, dict) else 'NOT A DICT'}")
execution_id = result.get("execution_id") or body.get("execution_id")
logger.info(f"Extracted execution_id: {execution_id}")
```

### Verify Import

```python
# At module level (line ~10)
logger.info("events.py: Importing evaluate_execution")
from .service import get_event_service, evaluate_execution
logger.info(f"events.py: evaluate_execution imported: {evaluate_execution}")
```

### Check Event Routing

Search for alternative event routing mechanisms that might bypass `/events` endpoint.

## Key Files

- `noetl/server/api/event/events.py` - Event creation endpoint (MODIFIED with logs)
- `noetl/server/api/event/service/core.py` - NEW broker system
- `noetl/server/api/event/service/initial.py` - First step dispatch (MODIFIED with logs)
- `noetl/server/api/event/service/queue.py` - Task enqueueing (MODIFIED with logs)
- `noetl/server/api/event/processing/broker.py` - OLD broker system (SUSPECT)

## Hypothesis

The execution flow is somehow calling the OLD `evaluate_broker_for_execution()` instead of the NEW `evaluate_execution()`, OR there's a completely different code path being used that we haven't identified yet.

The fact that `step_started` is created WITHOUT any of our debug logs appearing is the key clue - something is creating events outside our monitored code paths.

## Recommended Fix Strategy

1. **Add module-level import logging** to confirm evaluate_execution is imported
2. **Add function entry logging** to confirm create_event is called
3. **Log execution_id extraction** to see if it's None
4. **Search for alternative event creation paths** (direct database writes, old APIs, etc.)
5. **Once NEW system is confirmed working**, disable/remove OLD broker system

## Status

- ✅ Context refactoring completed successfully
- ✅ Service layer code correct with proper logging
- ❌ Service layer NOT BEING CALLED - root cause of all failures
- ⚠️ OLD broker system may still be active and interfering
