# Queue Meta Column and Parent Event Tracking

**Date**: 2025-10-29  
**Status**: Implemented ✅

## Problem Statement

The event tracking system had gaps in parent-child relationships:

1. **Missing `parent_event_id`**: Many events in the `event` table had `parent_event_id = null`, making it impossible to trace event lineage
2. **No `parent_execution_id` for sub-playbooks**: When a playbook calls another playbook, there was no way to track the parent execution
3. **No metadata channel from server to worker**: The queue table had no field for system metadata, so orchestration context couldn't be passed to workers

## Solution

### 1. Added `meta` Column to Queue Table

**Schema Change** (`noetl/database/ddl/postgres/schema_ddl.sql`):
```sql
CREATE TABLE IF NOT EXISTS noetl.queue (
    ...
    meta JSONB,  -- System metadata: parent event details, sub-playbook context, retry info
    ...
);
```

**Migration** (`noetl/database/migrations/20251029_add_queue_meta.sql`):
```sql
ALTER TABLE noetl.queue ADD COLUMN meta JSONB;
```

### 2. Server Populates Meta When Enqueueing Jobs

**Updated**: `noetl/server/api/queue/service.py`

```python
async def enqueue_job(..., parent_event_id, parent_execution_id, ...):
    # Build metadata for queue entry
    meta = {}
    if parent_event_id:
        meta['parent_event_id'] = parent_event_id
    if parent_execution_id:
        meta['parent_execution_id'] = parent_execution_id
    
    await cur.execute(
        """
        INSERT INTO noetl.queue (..., meta, ...)
        VALUES (..., %(meta)s, ...)
        """,
        {
            ...
            "meta": json.dumps(meta) if meta else None,
            ...
        }
    )
```

**Purpose**: Server now stores orchestration metadata in queue entries, ensuring workers have complete context.

### 3. Worker Extracts Meta and Adds to Events

**Updated**: `noetl/worker/worker.py`

```python
# Extract parent_event_id and parent_execution_id from queue meta
parent_event_id = None
parent_execution_id = None

# First priority: check queue meta (set by server when enqueueing)
try:
    job_meta = job.get('meta')
    if isinstance(job_meta, dict):
        parent_event_id = job_meta.get('parent_event_id')
        parent_execution_id = job_meta.get('parent_execution_id')
    elif isinstance(job_meta, str):
        # meta might be JSON string
        job_meta_parsed = json.loads(job_meta)
        if isinstance(job_meta_parsed, dict):
            parent_event_id = job_meta_parsed.get('parent_event_id')
            parent_execution_id = job_meta_parsed.get('parent_execution_id')
except Exception:
    pass

# Add to all events
start_event = {
    ...
    "parent_event_id": parent_event_id,
    "parent_execution_id": parent_execution_id
}
```

**Purpose**: Worker now reads meta from queue and includes parent tracking in all events (action_started, action_completed, action_failed, step_result).

## Data Flow

### Normal Step Execution

```
Server: Publish Step
  ↓
  └─> Enqueue Job with meta: {"parent_event_id": "workflow_initialized_event_id"}
       ↓
       Queue Entry: {parent_event_id: XXX, meta: {"parent_event_id": "XXX"}}
         ↓
         Worker: Lease Job
           ↓
           └─> Extract meta.parent_event_id
               ↓
               └─> Emit action_started with parent_event_id
                   ↓
                   Emit action_completed with parent_event_id
                     ↓
                     Emit step_result with parent_event_id
```

### Sub-Playbook Execution

```
Parent Execution (ID: 123)
  ↓
  └─> Step: Call sub-playbook
       ↓
       └─> Enqueue Job with meta: {
             "parent_event_id": "step_event_id",
             "parent_execution_id": 123
           }
           ↓
           Worker: Execute Sub-Playbook
             ↓
             └─> All events include:
                   execution_id: 456 (new)
                   parent_execution_id: 123 (original)
                   parent_event_id: "step_event_id"
```

## Benefits

1. **Complete Event Lineage**: Every event now has `parent_event_id`, allowing full trace reconstruction
2. **Sub-Playbook Tracking**: `parent_execution_id` enables tracking cross-execution hierarchies
3. **Extensible Metadata**: `meta` column can carry additional orchestration context (retry details, iteration index, etc.)
4. **Backward Compatible**: Legacy code paths still work via context metadata fallback

## Testing

**Verification Query**:
```sql
SELECT 
    event_id, 
    event_type, 
    node_name, 
    parent_event_id, 
    parent_execution_id 
FROM noetl.event 
WHERE execution_id = '<execution_id>' 
ORDER BY event_id;
```

**Expected Results**:
- ✅ `execution_started`: No parent (root event)
- ✅ `workflow_initialized`: parent_event_id = execution_started.event_id
- ✅ `action_started`: parent_event_id = workflow_initialized.event_id (or previous step's event_id)
- ✅ `action_completed`: parent_event_id = action_started.event_id
- ✅ `step_result`: parent_event_id = action_started.event_id

**Queue Verification**:
```sql
SELECT queue_id, node_name, parent_event_id, meta 
FROM noetl.queue 
WHERE execution_id = '<execution_id>';
```

**Expected Results**:
- ✅ `meta` column populated: `{"parent_event_id": "<event_id>"}`
- ✅ Matches `parent_event_id` column value

## Migration Steps

1. **Apply Migration**:
   ```bash
   psql -h localhost -p 54321 -U demo -d demo_noetl \
     -f noetl/database/migrations/20251029_add_queue_meta.sql
   ```

2. **Restart Services**:
   ```bash
   task noetl:local:stop && task noetl:local:start
   ```

3. **Verify**:
   ```bash
   # Run test execution
   curl -X POST http://localhost:8083/api/run/playbook \
     -H 'Content-Type: application/json' \
     -d '{"path": "tests/fixtures/playbooks/control_flow_workbook", "version": "1"}'
   
   # Check events
   psql -h localhost -p 54321 -U demo -d demo_noetl \
     -c "SELECT event_id, event_type, parent_event_id FROM noetl.event 
         WHERE execution_id = '<execution_id>' ORDER BY event_id;" -x
   ```

## Future Enhancements

1. **Iterator Context**: Store `current_index` and `current_item` in meta for loop iterations
2. **Distributed Tracing**: Add trace_id and span_id to meta for OpenTelemetry integration
3. **Retry Context**: Store original_queue_id and retry_reason in meta
4. **Performance Metrics**: Add timing metadata (enqueue_time, lease_time, execution_time)

## References

- Schema DDL: `noetl/database/ddl/postgres/schema_ddl.sql`
- Migration: `noetl/database/migrations/20251029_add_queue_meta.sql`
- Queue Service: `noetl/server/api/queue/service.py`
- Worker: `noetl/worker/worker.py`
- Event Tracking: `docs/event_tracking.md` (if exists)
