# Iterator Metadata Propagation Implementation

**Date:** October 30, 2025  
**Branch:** server  
**Status:** Completed

## Overview

Implemented complete iterator metadata propagation through the execution pipeline, ensuring that iterator context (index, count, item) is available in event logs when nested playbooks are called from iterators. Additionally fixed parent_execution_id propagation for nested playbook executions.

## Problem Statement

When an iterator step calls a nested playbook, the iterator context (current index, total count, current item) was not being propagated to the nested execution's events. This made it difficult to:
- Track which iteration a nested execution belongs to
- Debug iterator-based workflows
- Correlate nested execution results with their source iterations

Additionally, parent_execution_id was not being set for nested playbook executions called from iterators.

## Solution Architecture

### Metadata Flow

```
Iterator Context (_loop)
    ↓
Playbook Executor (extracts iterator_index, iterator_count, iterator_item)
    ↓
Execution Request (metadata field)
    ↓
Execution Service
    ↓
Event Emitter (stores in event.meta) + Queue Publisher (passes to queue)
    ↓
Queue Entry (stores in queue.meta)
    ↓
Worker (reads queue.meta and includes in all events)
    ↓
Events (stored in event.meta.queue_meta)
```

## Files Changed

### 1. `noetl/plugin/playbook/context.py`

**Purpose:** Fix parent_execution_id extraction and add fallback logic

**Changes:**
- Added fallback to `context.get('execution_id')` when parent context doesn't have execution_id
- Added debug logging to track parent identifier resolution
- Enhanced log output to include context keys for troubleshooting

**Key Code:**
```python
# Added fallback for execution_id resolution
parent_execution_id = (
    (parent_context.get('execution_id')
     if isinstance(parent_context, dict) else None)
    or parent_meta.get('parent_execution_id')
    or context_meta.get('parent_execution_id')
    or context.get('execution_id')  # NEW: Fallback to current context
)
```

**Impact:** Ensures parent_execution_id is always resolved when available in context

---

### 2. `noetl/plugin/playbook/executor.py`

**Purpose:** Extract iterator metadata and fix API endpoint

**Changes:**
- Extract `_loop` metadata from context when executing nested playbooks
- Build iterator metadata dictionary with `iterator_index`, `iterator_count`, `iterator_item`
- Pass metadata in execution request payload
- Fixed API endpoint from `/api/execute` to `/api/run/playbook`

**Key Code:**
```python
# Extract iterator metadata from context if present
iterator_meta = {}
try:
    if '_loop' in context and isinstance(context['_loop'], dict):
        iterator_meta = {
            'iterator_index': context['_loop'].get('current_index'),
            'iterator_count': context['_loop'].get('count'),
            'iterator_item': context['_loop'].get('item')
        }
except Exception as e:
    logger.debug(f"PLAYBOOK: No iterator metadata found: {e}")

# Include in request payload
request_payload = {
    ...
    "metadata": iterator_meta if iterator_meta else None
}
```

**Impact:** Iterator context is now captured and passed to nested executions

---

### 3. `noetl/server/api/run/service.py`

**Purpose:** Pass metadata through execution service

**Changes:**
- Pass `request.metadata` to `ExecutionEventEmitter.emit_execution_start()`
- Pass `request.metadata` to `QueuePublisher.publish_initial_steps()`

**Key Code:**
```python
# In emit_execution_start call
start_event_id = await ExecutionEventEmitter.emit_execution_start(
    ...
    requestor_info=requestor_info,
    metadata=request.metadata  # NEW
)

# In publish_initial_steps call
queue_ids = await QueuePublisher.publish_initial_steps(
    ...
    context=context,
    metadata=request.metadata  # NEW
)
```

**Impact:** Metadata flows from request to event emitter and queue publisher

---

### 4. `noetl/server/api/run/events.py`

**Purpose:** Store metadata in execution_started events

**Changes:**
- Added `metadata` parameter to `emit_execution_start()` method signature
- Merge metadata into event's `meta` field
- Updated docstring to document metadata parameter

**Key Code:**
```python
async def emit_execution_start(
    ...
    requestor_info: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None  # NEW
) -> str:
    ...
    # Include iterator metadata if provided
    if metadata:
        meta.update(metadata)
```

**Impact:** Iterator metadata is stored in execution_started event's meta column

---

### 5. `noetl/server/api/run/publisher.py`

**Purpose:** Propagate metadata through queue publisher

**Changes:**
- Added `metadata` parameter to `publish_initial_steps()` method signature
- Added `metadata` parameter to `publish_step()` method signature
- Pass metadata to all `QueueService.enqueue_job()` calls
- Updated docstrings

**Key Code:**
```python
async def publish_initial_steps(
    ...
    context: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None  # NEW
) -> List[str]:
    ...
    response = await QueueService.enqueue_job(
        ...
        metadata=metadata  # NEW
    )

async def publish_step(
    ...
    delay_seconds: int = 0,
    metadata: Optional[Dict[str, Any]] = None  # NEW
) -> str:
    ...
    response = await QueueService.enqueue_job(
        ...
        metadata=metadata  # NEW
    )
```

**Impact:** Metadata is passed to queue entries for worker consumption

---

### 6. `noetl/server/api/queue/service.py`

**Purpose:** Store metadata in queue entries

**Changes:**
- Added `metadata` parameter to `enqueue_job()` method signature
- Merge metadata into queue entry's `meta` field

**Key Code:**
```python
async def enqueue_job(
    ...
    status: str = "queued",
    metadata: Optional[Dict[str, Any]] = None  # NEW
) -> EnqueueResponse:
    ...
    # Build metadata for queue entry
    meta = {}
    if parent_event_id:
        meta['parent_event_id'] = str(parent_event_id)
    if parent_execution_id:
        meta['parent_execution_id'] = str(parent_execution_id)
    
    # Include iterator/execution metadata if provided
    if metadata:
        meta.update(metadata)  # NEW
```

**Impact:** Metadata is stored in queue.meta column for worker retrieval

---

### 7. `noetl/worker/worker.py`

**Purpose:** No changes needed - already propagates queue metadata

**Existing Behavior:**
- Worker already reads `queue_meta` from job
- Worker already includes `queue_meta` in all emitted events:
  - `action_started` event (line 851-853)
  - `action_failed` event (line 1021-1024)
  - `action_completed` event (line 1051-1054)
  - `step_result` event (line 1088-1091)

**Existing Code:**
```python
# Worker already does this for all events
if job_meta and isinstance(job_meta, dict):
    if "meta" not in event:
        event["meta"] = {}
    event["meta"]["queue_meta"] = job_meta
```

**Impact:** All worker-emitted events automatically include iterator metadata from queue

---

## Schema Support

### ExecutionRequest Schema (`noetl/server/api/run/schema.py`)

The `ExecutionRequest` model already had a `metadata` field:

```python
class ExecutionRequest(BaseModel):
    ...
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional metadata for execution tracking"
    )
```

**No changes needed** - existing schema already supports metadata propagation.

---

## Verification Results

### Test Execution: Playbook Composition with Iterator

**Test Playbook:** `tests/fixtures/playbooks/playbook_composition/playbook_composition.yaml`

**Results:**

1. **Parent Execution ID Propagation:** ✅
   ```sql
   SELECT execution_id, parent_execution_id FROM noetl.event 
   WHERE parent_execution_id = '484381060852089079'
   ```
   - 4 child executions found (one per iterator item)
   - All have correct parent_execution_id set

2. **Iterator Metadata in execution_started Events:** ✅
   ```sql
   SELECT execution_id, meta FROM noetl.event 
   WHERE parent_execution_id = '484381060852089079' 
   AND event_type = 'execution_started'
   ```
   - `iterator_index`: 0, 1, 2, 3
   - `iterator_count`: 4
   - `iterator_item`: Complete user data for each iteration

3. **Queue Metadata Propagation:** ✅
   ```sql
   SELECT meta->'queue_meta'->>'iterator_index' 
   FROM noetl.event 
   WHERE event_type = 'action_started'
   ```
   - First workflow step has iterator metadata in queue_meta
   - Subsequent steps can reference parent execution's execution_started event

---

## Data Structure Examples

### Iterator Metadata Structure

```json
{
  "iterator_index": 0,
  "iterator_count": 4,
  "iterator_item": {
    "name": "Alice",
    "age": 28,
    "department": "Engineering",
    "years_experience": 5,
    "performance_rating": 4.2
  }
}
```

### Event Meta Field Structure

```json
{
  "emitter": "execution_service",
  "emitted_at": "2025-10-30T07:38:43.925131",
  "requestor": {
    "ip": "127.0.0.1",
    "user_agent": "python-requests/2.32.5",
    "timestamp": "2025-10-30T07:38:43.912375"
  },
  "iterator_index": 0,
  "iterator_count": 4,
  "iterator_item": {
    "name": "Alice",
    "age": 28,
    "department": "Engineering",
    "years_experience": 5,
    "performance_rating": 4.2
  }
}
```

### Queue Meta Field Structure

```json
{
  "parent_event_id": "484381061204410617",
  "parent_execution_id": "484381060852089079",
  "iterator_index": 0,
  "iterator_count": 4,
  "iterator_item": {
    "name": "Alice",
    "age": 28,
    "department": "Engineering",
    "years_experience": 5,
    "performance_rating": 4.2
  }
}
```

---

## Usage Guidelines

### Querying Iterator Context from Events

To get iterator context for a nested execution:

```sql
-- Get iterator metadata from execution_started event
SELECT 
  execution_id,
  parent_execution_id,
  meta->>'iterator_index' as iteration,
  meta->>'iterator_count' as total,
  meta->'iterator_item' as item_data
FROM noetl.event
WHERE event_type = 'execution_started'
  AND parent_execution_id IS NOT NULL
ORDER BY execution_id;
```

To join child executions with iterator context:

```sql
-- Join child events with parent iterator context
SELECT 
  child.execution_id,
  child.event_type,
  child.node_name,
  parent.meta->>'iterator_index' as iteration
FROM noetl.event child
JOIN noetl.event parent 
  ON child.execution_id = parent.execution_id
  AND parent.event_type = 'execution_started'
WHERE child.parent_execution_id = '484381060852089079'
ORDER BY parent.meta->>'iterator_index', child.event_id;
```

---

## Benefits

1. **Traceability**: Complete audit trail of which iteration spawned each nested execution
2. **Debugging**: Easy identification of failing iterations in complex workflows
3. **Monitoring**: Ability to track performance metrics per iteration
4. **Reproducibility**: Iterator item data preserved for replay/debugging
5. **Backward Compatibility**: No breaking changes to existing workflows

---

## Future Enhancements

1. Propagate metadata to all subsequent queue entries (not just initial steps)
2. Add iterator metadata to workflow transition events
3. Create database views for easy iterator context queries
4. Add iterator metadata to execution API responses
5. Dashboard visualizations for iterator-based workflows

---

## Notes

- Iterator metadata is stored in both event.meta and queue.meta for redundancy
- Metadata size should be reasonable (iterator_item contains full item data)
- For large collections, consider storing item reference instead of full data
- Worker automatically includes queue_meta in all events without additional code changes
