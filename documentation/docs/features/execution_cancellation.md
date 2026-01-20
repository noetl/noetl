---
sidebar_position: 25
---

# Execution Cancellation

NoETL provides the ability to cancel running executions. This is useful for terminating runaway workflows, stopping infinite loops, or aborting executions that are no longer needed.

## Overview

The cancellation system works by:

1. Creating an `execution.cancelled` event in the event table
2. Workers checking for cancellation before executing commands
3. Optionally cascading cancellation to child executions (sub-playbooks)

## CLI Usage

### Cancel an Execution

```bash
# Basic cancellation
noetl cancel <execution_id>

# With a reason
noetl cancel 543857931469455628 --reason "Detected infinite loop"

# Cascade to child executions (sub-playbooks)
noetl cancel 543857931469455628 --cascade

# JSON output
noetl cancel 543857931469455628 --json
```

### Example Output

```
============================================================
Execution: 543857931469455628
Status:    CANCELLED
Cancelled: 1 execution(s)
Message:   Cancelled 1 execution(s)
Reason:    Detected infinite loop
============================================================
```

### With Cascade

When an execution has spawned sub-playbooks (child executions), use `--cascade` to cancel all of them:

```bash
noetl cancel 543857931469455628 --cascade
```

Output:
```
============================================================
Execution: 543857931469455628
Status:    CANCELLED
Cancelled: 3 execution(s)
Message:   Cancelled 3 execution(s)

Cancelled executions:
  - 543857931469455628
  - 543857932012345678
  - 543857933098765432
============================================================
```

## API Endpoints

### Cancel Execution

**Endpoint:** `POST /api/executions/{execution_id}/cancel`

**Request Body:**
```json
{
  "reason": "Optional cancellation reason",
  "cascade": true
}
```

**Response:**
```json
{
  "status": "cancelled",
  "execution_id": "543857931469455628",
  "cancelled_executions": [
    "543857931469455628"
  ],
  "message": "Cancelled 1 execution(s)"
}
```

**Error Response (already completed):**
```json
{
  "status": "error",
  "execution_id": "543857931469455628",
  "cancelled_executions": [],
  "message": "Execution 543857931469455628 is already COMPLETED"
}
```

### Check Cancellation Status

Workers use this endpoint to check if an execution has been cancelled before executing commands.

**Endpoint:** `GET /api/executions/{execution_id}/cancellation-check`

**Response:**
```json
{
  "execution_id": "543857931469455628",
  "status": "CANCELLED",
  "event_type": "execution.cancelled",
  "cancelled": true,
  "completed": false,
  "failed": false
}
```

## How It Works

### Event-Driven Cancellation

1. When you call the cancel endpoint, NoETL creates an `execution.cancelled` event:
   ```sql
   INSERT INTO noetl.event (event_type, status, ...)
   VALUES ('execution.cancelled', 'CANCELLED', ...);
   ```

2. Workers periodically check for cancellation by querying this endpoint before executing commands.

3. If cancelled, workers emit a `command.cancelled` event and skip execution.

### Cascade Cancellation

When `cascade: true` is specified:

1. The server finds all child executions using `parent_execution_id`:
   ```sql
   WITH RECURSIVE children AS (
     SELECT execution_id FROM noetl.event WHERE execution_id = <id>
     UNION ALL
     SELECT e.execution_id
     FROM noetl.event e
     JOIN children c ON e.parent_execution_id = c.execution_id
   )
   SELECT DISTINCT execution_id FROM children;
   ```

2. Creates `execution.cancelled` events for all found executions.

### Worker Behavior

Workers check for cancellation at two points:

1. **Before claiming**: Checks if execution is cancelled before attempting to claim a command
2. **After claiming**: Checks again after successfully claiming (in case cancellation happened during claim)

If cancelled, the worker:
- Logs the cancellation
- Emits a `command.cancelled` event
- Skips execution of the command

## Use Cases

### 1. Stopping Infinite Loops

If a playbook has a bug causing an infinite loop:

```bash
# Identify the runaway execution
noetl status <execution_id>

# Cancel it
noetl cancel <execution_id> --reason "Infinite loop detected"
```

### 2. Aborting Long-Running Jobs

For long-running data processing jobs that are no longer needed:

```bash
noetl cancel <execution_id> --reason "Data already processed by another job"
```

### 3. Cancelling Hierarchical Workflows

For workflows that spawn multiple sub-playbooks:

```bash
# Cancel parent and all children
noetl cancel <parent_execution_id> --cascade
```

### 4. Emergency Stop

In production, you can cancel executions via the API:

```bash
curl -X POST "http://localhost:8082/api/executions/543857931469455628/cancel" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Emergency stop", "cascade": true}'
```

### 5. Batch Cleanup of Stale Executions

When multiple executions become stale (e.g., after server restart or worker crashes), you can cancel them in a batch using a shell loop:

```bash
# Cancel multiple stale executions
for id in 543861711535604109 543857931469455628 543857817971589380 543853604759666866; do
  echo "Cancelling $id..."
  noetl cancel $id --reason "Cleanup stale execution" 2>/dev/null || echo "  (already cancelled or completed)"
done
```

Example output:
```
Cancelling 543861711535604109...

============================================================
Execution: 543861711535604109
Status:    CANCELLED
Cancelled: 1 execution(s)
Message:   Cancelled 1 execution(s)
Reason:    Cleanup stale execution
============================================================

Cancelling 543857931469455628...
  (already cancelled or completed)
```

You can also query for stale executions first and then cancel them:

```bash
# Find executions stuck in RUNNING/INITIALIZED for more than 10 minutes
noetl query "SELECT DISTINCT execution_id 
             FROM noetl.event 
             WHERE status IN ('RUNNING', 'INITIALIZED') 
               AND created_at < NOW() - INTERVAL '10 minutes'
             ORDER BY execution_id DESC"
```

## Limitations

1. **Not Instantaneous**: Workers check for cancellation periodically. A command already in progress will complete before the worker checks again.

2. **Event-Based**: Cancellation is recorded as an event. The execution state is derived from events, so cancellation takes effect when the next command is about to be processed.

3. **No Rollback**: Cancellation stops future commands but does not roll back already completed steps.

## Monitoring Cancelled Executions

Query cancelled executions:

```bash
noetl query "SELECT execution_id, created_at, context->>'reason' as reason 
             FROM noetl.event 
             WHERE event_type = 'execution.cancelled' 
             ORDER BY created_at DESC 
             LIMIT 10"
```

## Related Commands

- `noetl status <execution_id>` - Check execution status
- `noetl query` - Query event table directly
