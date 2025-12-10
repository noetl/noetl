---
sidebar_position: 8
---

# Distributed Loop and Retry Architecture

## Overview

NoETL implements a fully distributed, event-driven architecture for loop iteration and retry logic. This architecture ensures complete traceability, scalability, and fault tolerance by routing all control flow through the server-worker event loop rather than executing loops and retries in-process within workers.

**Status: Phase 1 Complete ✅**
- Worker-side event emission implemented
- Iterator executor analyzes collections and emits events
- Event schema extended with iterator types
- Context sanitization for safe event storage

**Status: Phase 2 Pending ⏳**
- Server orchestration of iteration jobs
- Iteration execution with pagination
- Result aggregation

## Core Principle: Event-Driven Control Loop

**Every action must pass through the server-worker control loop for traceability and distributed computation.**

The control loop cycle:
```
Worker executes task
    ↓
Worker reports EVENT via /api/events
    ↓
Server receives event → evaluate_execution()
    ↓
Server reconstructs state from events
    ↓
Server enqueues next tasks to QUEUE
    ↓
Worker picks up from queue
    ↓
Repeat
```

## Loop Architecture

### Event-Driven Implementation (Phase 1 Complete)

```
1. Worker receives loop task
   ↓
2. Worker analyzes collection (count, metadata)
   ↓
3. Worker reports iterator_started event with:
   - Collection size (total_count, collection_size)
   - Iterator configuration (mode, iterator_name, etc.)
   - Nested task definition (HTTP action, pagination config)
   - Full collection metadata
   ↓
4. Server processes iterator_started event (⏳ PENDING)
   ↓
5. Server enqueues N jobs (one per iteration/batch) with:
   - parent_execution_id = loop execution_id
   - iteration_index in job payload
   - Element/batch data
   ↓
6. Workers (potentially multiple) pick up iteration jobs
   ↓
7. Each worker executes one iteration
   ↓
8. Each worker reports iteration_completed event
   ↓
9. Server tracks completion counter
   ↓
10. When all iterations complete, server reports iterator_completed
    ↓
11. Server continues with next workflow step
```

### Loop Event Lifecycle

#### Phase 1 (✅ Implemented)

```yaml
# Step 1: Worker analyzes loop task
- event: iterator_started
  status: RUNNING
  context:
    iterator_name: "endpoint"
    total_count: 2
    collection_size: 2
    mode: "sequential"
    collection:
      - name: "assessments"
        path: "/api/v1/assessments"
        page_size: 10
      - name: "users"
        path: "/api/v1/users"
        page_size: 15
    nested_task:
      tool: "http"
      retry:
        - when: "{{ response.paging.hasMore == true }}"
          then:
            max_attempts: 10
            collect:
              strategy: "append"
              path: "data"
```

#### Phase 2 (⏳ Pending)

```yaml
# Step 2: Server enqueues iteration jobs (N jobs)
# (Queue entries created, not events)

# Step 3: Workers execute iterations (parallel if async mode)
- event: iteration_started
  parent_execution_id: <loop_execution_id>
  data:
    iteration_index: 0
    element: {...}

- event: iteration_completed
  parent_execution_id: <loop_execution_id>
  data:
    iteration_index: 0
    result: {...}
    status: "success"

# ... repeat for each iteration ...

# Step 4: Server detects all iterations complete
- event: iterator_completed
  data:
    total_iterations: 2
    successful: 2
    failed: 0
    results: [...]  # Aggregated results in order
```

### Loop Configuration Example

```yaml
- step: fetch_all_endpoints
  tool: http
  url: "{{ server_url }}{{ endpoint.path }}"
  params:
    page: 1
    page_size: "{{ endpoint.page_size }}"
  loop:
    collection: "{{ workload.endpoints }}"  # Template evaluation
    element: endpoint                       # Iterator variable
    mode: sequential                        # Processing mode
  retry:
    - when: "{{ response.paging.hasMore }}"  # Pagination trigger
      then:
        max_attempts: 10
        collect:
          strategy: append
          path: data
```

**Supported Processing Modes:**
- `sequential`: Process one element at a time (tested)
- `async`: Process all elements concurrently (designed)
- `chunked`: Process in batches (designed)

### Loop Sink (Per-Iteration Save)

Each iteration can have a `sink` block that saves results to storage:

```yaml
- step: process_users
  tool: http
  url: "{{ api_url }}/process"
  loop:
    collection: "{{ users }}"
    element: user
    mode: async
    concurrency: 10
  sink:
    tool: postgres
    table: processed_users
    auth:
      type: postgres
      credential: main_db
```

**Sink Execution Flow:**
1. Worker executes iteration (HTTP call)
2. Worker executes sink (save to Postgres) **in same job**
3. If sink fails, entire iteration fails (atomic transaction)
4. Worker reports iteration result (success/failed)

**Sink operates as single transaction with iteration - if sink fails, iteration fails.**

## Retry Architecture

### Retry on Error (Failure Retry)

```
1. Worker receives task with retry.on_error config
   ↓
2. Worker executes task
   ↓
3. Task fails
   ↓
4. Worker reports action_failed event with retry metadata:
   - retry_config (max_attempts, backoff, etc.)
   - attempt_number = 1
   ↓
5. Server processes action_failed event
   ↓
6. Server checks retry config:
   - attempt_number < max_attempts?
   - Error matches retry condition?
   ↓
7. If should retry:
   - Server waits backoff delay (or schedules future job)
   - Server re-enqueues same task with:
     * parent_event_id = original event_id
     * attempt_number = attempt_number + 1
   ↓
8. Worker picks up retry job
   ↓
9. Worker executes (reports original task, not "retry task")
   ↓
10. Repeat until success or max_attempts reached
```

### Retry on Success (Pagination/Polling)

```
1. Worker receives task with retry.on_success config
   ↓
2. Worker executes task (e.g., HTTP call)
   ↓
3. Task succeeds
   ↓
4. Worker reports action_completed event with:
   - Result data
   - retry_config with while condition
   - attempt_number = 1
   ↓
5. Server processes action_completed event
   ↓
6. Server evaluates retry.while condition:
   - Template rendering: "{{ response.paging.hasMore }}"
   - Using response data from event
   ↓
7. If should continue:
   - Server applies next_call transformations
   - Server re-enqueues task with:
     * Updated params (next page, etc.)
     * parent_event_id = previous event_id
     * attempt_number = attempt_number + 1
   ↓
8. Worker picks up continuation job
   ↓
9. Worker executes next iteration
   ↓
10. Repeat until while condition false or max_attempts reached
    ↓
11. Server aggregates results based on collect strategy
```

### Retry Event Lifecycle

#### On Error Example

```yaml
# Attempt 1
- event: action_started
  data:
    step: "fetch_data"
    tool: "http"
    retry_config:
      - when: "{{ error is defined }}"
        then:
          max_attempts: 3
          backoff: exponential

- event: action_failed
  data:
    step: "fetch_data"
    error: "Connection timeout"
    attempt_number: 1

# Server decides to retry (attempt < max_attempts)
# Server re-enqueues job with backoff delay

# Attempt 2
- event: action_started
  parent_event_id: <first_attempt_event_id>
  data:
    step: "fetch_data"
    attempt_number: 2

- event: action_completed
  parent_event_id: <first_attempt_event_id>
  data:
    step: "fetch_data"
    result: {...}
    attempt_number: 2
```

#### On Success Example (Pagination)

```yaml
# Page 1
- event: action_completed
  data:
    step: "fetch_users"
    result:
      data: [10 items]
      paging:
        hasMore: true
        page: 1
    retry_config:
      - when: "{{ response.paging.hasMore }}"
        then:
          next_call:
            params:
              page: "{{ response.paging.page + 1 }}"
    attempt_number: 1

# Server evaluates: hasMore = true, continue
# Server re-enqueues with updated params

# Page 2
- event: action_completed
  parent_event_id: <page1_event_id>
  data:
    step: "fetch_users"
    result:
      data: [10 items]
      paging:
        hasMore: true
        page: 2
    attempt_number: 2

# ... continues until hasMore = false ...

# Final aggregation
- event: retry_sequence_completed
  data:
    step: "fetch_users"
    total_attempts: 4
    aggregated_result: [40 items total]
```

### Retry Sink (Per-Attempt Save)

Each retry attempt can save its result independently:

```yaml
- step: fetch_paginated_data
  tool: http
  url: "{{ api_url }}/data"
  params:
    page: 1
    pageSize: 100
  retry:
    - when: "{{ response.paging.hasMore }}"
      then:
        max_attempts: 100
        next_call:
          params:
            page: "{{ response.paging.page + 1 }}"
        collect:
          strategy: append
          path: data
  sink:
    tool: postgres
    table: raw_data
    auth:
      type: postgres
      credential: main_db
    mode: append
```

**Sink Execution Flow:**
1. Worker executes HTTP call (gets page 1)
2. Worker executes sink (saves page 1 to Postgres)
3. If sink fails, entire attempt fails
4. Worker reports action_completed with result
5. Server evaluates retry condition (hasMore = true)
6. Server re-enqueues for page 2
7. Worker executes page 2 + sink
8. Repeat until hasMore = false

**Each retry attempt is atomic with its sink - if sink fails, that attempt fails.**

## Independence of Loop and Retry

Loop and retry are **completely independent wrappers** that can be combined:

### Loop Without Retry
```yaml
- step: process_items
  tool: python
  code: |
    def main(item):
      return item * 2
  loop:
    collection: "{{ items }}"
    element: item
```

### Retry Without Loop
```yaml
- step: fetch_data
  tool: http
  url: "{{ api_url }}/data"
  retry:
    - when: "{{ response.paging.hasMore }}"
      then:
        next_call:
          params:
            page: "{{ response.paging.page + 1 }}"
```

### Loop With Retry (Nested)
```yaml
- step: fetch_multiple_apis
  tool: http
  url: "{{ endpoint }}/data"
  params:
    page: 1
  loop:
    collection: "{{ endpoints }}"
    element: endpoint
  retry:
    - when: "{{ response.paging.hasMore }}"
      then:
        next_call:
          params:
            page: "{{ response.paging.page + 1 }}"
```

**Execution flow for nested loop+retry:**
1. Server enqueues N jobs (one per endpoint)
2. Worker 1 executes endpoint[0], page 1
3. Worker 1 reports completion with hasMore=true
4. Server re-enqueues endpoint[0], page 2
5. Meanwhile, Worker 2 picks up endpoint[1], page 1
6. Continue until all endpoints, all pages complete

## Database Tracking Fields

The event and queue tables support parent-child relationships for distributed execution:

- **execution_id**: Current execution identifier
- **parent_execution_id**: Links child execution to parent (e.g., iteration to loop)
- **event_id**: Current event identifier
- **parent_event_id**: Links retry attempt to original event
- **queue_id**: Tracks which queue entry spawned this execution

## Metadata and Context Tracking

### Event Context Column

The `noetl.event` table has a `context JSONB` column for execution state tracking.

#### Context Sanitization

Worker sanitizes context before sending to server:

**Included in Context:**
- `execution_id`, `job_id`, `catalog_id` - Execution identifiers
- `workload` - Global workflow variables
- `vars` - Extracted variables from steps
- `_step_results` - Summary of step results (metadata only, not full data)

**Size Limits:**
- Large objects (>10KB) are truncated with metadata: `{"_truncated": true, "_size": 12345}`
- Step results include only metadata: `{"has_data": true, "status": "success", "data_type": "dict"}`

**Excluded from Context:**
- Sensitive credentials (never included)
- Full step result data (only metadata/summary)
- Internal keys starting with `_` (except `_step_results`)

#### Context Flow

```
Worker builds execution context
    ↓
Worker sanitizes context (_sanitize_context_for_event)
    ↓
Worker emits event via /api/events
    ↓
Server stores in event.context column
    ↓
Server reads context to reconstruct state
    ↓
Server uses context for next step evaluation
```

### Event Metadata Column

Both `noetl.queue` and `noetl.event` tables have `meta JSONB` columns for structured metadata tracking.

#### Queue Metadata (Server-Side)

**Iterator Jobs:**
```json
{
  "iterator": {
    "parent_execution_id": 123456,
    "iteration_index": 0,
    "total_iterations": 100,
    "iterator_name": "item",
    "mode": "async"
  }
}
```

**Retry Jobs (on_error):**
```json
{
  "retry": {
    "type": "on_error",
    "attempt_number": 2,
    "max_attempts": 3,
    "parent_event_id": "789012",
    "backoff_seconds": 4,
    "scheduled_at": "2025-12-06T10:30:00Z"
  }
}
```

**Retry Jobs (on_success - pagination):**
```json
{
  "retry": {
    "type": "on_success",
    "attempt_number": 2,
    "max_attempts": 100,
    "parent_event_id": "789012",
    "continuation": "pagination"
  }
}
```

#### Event Metadata (Worker-Side)

**Action Completed Events:**
```json
{
  "retry": {
    "has_config": true,
    "attempt_number": 1,
    "max_attempts": 3,
    "retry_type": "on_success"
  },
  "execution": {
    "duration_seconds": 1.234,
    "completed_at": "2025-12-06T10:30:00Z"
  }
}
```

**Action Failed Events:**
```json
{
  "retry": {
    "has_config": true,
    "attempt_number": 1,
    "max_attempts": 3,
    "retry_type": "on_error",
    "will_retry": true
  },
  "execution": {
    "duration_seconds": 0.567
  },
  "error": {
    "message": "Connection timeout (truncated to 500 chars)",
    "has_stack_trace": true,
    "failed_at": "2025-12-06T10:30:00Z"
  }
}
```

**Iterator Started Events:**
```json
{
  "iterator": {
    "iterator_name": "endpoint",
    "total_count": 2,
    "collection_size": 2,
    "mode": "sequential"
  },
  "execution": {
    "started_at": "2025-12-06T10:30:00Z"
  }
}
```

### Event Data Structure

Events sent to server API include:

```json
{
  "execution_id": 123456,
  "catalog_id": 789,
  "node_id": "fetch_data",
  "node_name": "fetch_data",
  "event_type": "action_completed",
  "status": "COMPLETED",
  "node_type": "http",
  "duration": 1.234,
  "result": {"id": "...", "status": "success", "data": {...}},
  "context": {
    "execution_id": 123456,
    "workload": {"api_url": "https://api.example.com"},
    "vars": {"user_id": "12345"},
    "_step_results": {
      "previous_step": {
        "has_data": true,
        "status": "success",
        "data_type": "dict"
      }
    }
  },
  "data": {
    "result": {...},
    "retry_config": [
      {
        "when": "{{ response.paging.hasMore }}",
        "then": {
          "max_attempts": 100
        }
      }
    ],
    "attempt_number": 1
  },
  "meta": {
    "retry": {
      "has_config": true,
      "attempt_number": 1,
      "max_attempts": 100,
      "retry_type": "on_success"
    },
    "execution": {
      "duration_seconds": 1.234,
      "completed_at": "2025-12-06T10:30:00Z"
    }
  },
  "parent_event_id": "789012",
  "parent_execution_id": 345678
}
```

## Implementation Status

### Phase 1: Worker-Side Event Emission (✅ Complete)

**Implemented Components:**

1. **Event Callback Integration** (`noetl/plugin/runtime/execution.py`)
   - Added `event_callback` parameter to `execute_task()`
   - Passes callback to `execute_iterator_task()`
   - Worker-side sync→async event emission bridge

2. **Iterator Executor** (`noetl/plugin/controller/iterator/executor.py`)
   - Collection analysis (count, metadata extraction)
   - `iterator_started` event emission with full context
   - Nested task configuration included in event
   - Status values: `RUNNING`, `FAILED` (uppercase)

3. **Event Schema** (`noetl/server/api/broker/schema.py`)
   - Extended `EventType` Literal with iterator types:
     - `iterator_started`
     - `iterator_completed`
     - `iterator_failed`
     - `iteration_completed`
     - `retry_scheduled`

4. **Context Sanitization** (`noetl/worker/queue_worker.py`)
   - Safe event payload construction
   - Field mapping (node_name/node_type)
   - execution_id as string
   - AsyncIO event emission in thread pool

**Validation:**
- Test playbook: `tests/fixtures/playbooks/pagination/loop_with_pagination/`
- Test notebook validates event emission and metadata
- `iterator_started` event successfully stored in database

### Phase 2: Server-Side Orchestration (⏳ Pending)

**Required Implementation:**

1. **Orchestrator Handler** (`noetl/server/api/orchestrator/orchestrator.py`)
   ```python
   async def _process_iterator_started(self, execution_id: int, event: Dict[str, Any]):
       """Enqueue iteration jobs from iterator_started event."""
       context = event.get('context', {})
       collection = context.get('collection', [])
       nested_task = context.get('nested_task', {})
       
       for idx, element in enumerate(collection):
           job_data = {
               'execution_id': execution_id,
               'iteration_index': idx,
               'element': element,
               'task_config': nested_task
           }
           await self._enqueue_job(job_data)
   ```

2. **Event Handler Registration**
   ```python
   event_handlers = {
       'iterator_started': self._process_iterator_started,
       'iteration_completed': self._process_iteration_completed,
       # ... existing handlers
   }
   ```

3. **Iteration Tracking**
   - Track completion counter per execution_id
   - Detect when all iterations complete
   - Emit `iterator_completed` event
   - Continue workflow to next step

4. **Result Aggregation**
   - Collect results from `iteration_completed` events
   - Apply collection strategy (append, replace, collect)
   - Store aggregated result in final event

### Phase 3: Advanced Features (🔮 Designed)

- Scheduled retry jobs (backoff in database)
- Concurrent iteration execution
- Chunk processing for large collections
- Iterator result streaming
- Retry circuit breaker
- Context-based workflow branching

## Benefits of Distributed Architecture

1. **Traceability**: Every iteration and retry tracked in event log
2. **Observability**: Real-time monitoring of progress
3. **Failure Handling**: Granular retry at iteration level
4. **Resource Efficiency**: Workers don't block for entire loop/retry sequence
5. **Scalability**: Multiple workers can process iterations in parallel
6. **Fault Tolerance**: Worker crash doesn't lose entire loop progress
7. **Debugging**: Can inspect state between iterations/retries
8. **Fairness**: Short tasks don't wait behind long loops
9. **Complete State Reconstruction**: Server rebuilds execution state from context
10. **Distributed Coordination**: Context flows through server API, no direct database access

## Testing

See the comprehensive test implementation:
- **Test Playbook**: `tests/fixtures/playbooks/pagination/loop_with_pagination/`
- **Test Notebook**: `pagination_loop_test.ipynb`
- **README**: Complete validation guide and architecture explanation

The test validates:
- ✅ Loop detection and routing
- ✅ Iterator executor collection analysis
- ✅ `iterator_started` event emission
- ✅ Event schema compliance
- ✅ Context metadata (collection, nested_task, pagination config)
- ⏳ Server orchestration (pending Phase 2)

## Related Documentation

- [Retry Mechanism](./retry_mechanism.md)
- [Pagination](./pagination.md)
- [Playbook Structure](./playbook_structure.md)
- [Variables](./variables.md)
