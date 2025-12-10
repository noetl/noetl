# Distributed Loop and Retry Architecture

:::warning Document Relocated
This document has been moved to the main documentation site:
**[documentation/docs/features/distributed_loop_retry_architecture.md](../documentation/docs/features/distributed_loop_retry_architecture.md)**

The content below is kept for backward compatibility but may be outdated.
:::

## Core Principle: Event-Driven Control Loop

**Every action must pass through the server-worker control loop for traceability and distributed computation.**

The control loop cycle:
```
Worker executes task
    ↓
Worker reports EVENT via /api/v1/event/emit
    ↓
Server receives event → orchestrator.evaluate_execution()
    ↓
Server reconstructs state from events
    ↓
Server publishes next tasks to QUEUE via QueueService.enqueue_job()
    ↓
Worker picks up from queue
    ↓
Repeat
```

## Database Tracking Fields

The event and queue tables support parent-child relationships for distributed execution:

- **execution_id**: Current execution identifier
- **parent_execution_id**: Links child execution to parent (e.g., iteration to loop)
- **event_id**: Current event identifier
- **parent_event_id**: Links retry attempt to original event
- **queue_id**: Tracks which queue entry spawned this execution

## Loop Architecture

### Current (Incorrect) Implementation

```
Worker receives loop task
    ↓
Worker executes ALL iterations in-process (ThreadPoolExecutor)
    ↓
Worker aggregates results
    ↓
Worker returns final result
```

**Problems:**
- Violates distributed computation principle
- No event traceability for individual iterations
- Cannot handle failures at iteration level
- Blocks worker for entire loop duration
- Cannot distribute iterations across multiple workers

### Correct (Event-Driven) Implementation

```
1. Worker receives loop task
   ↓
2. Worker analyzes collection (count, metadata)
   ↓
3. Worker reports iterator_started event with:
   - Collection size
   - Iterator configuration (mode, concurrency, etc.)
   ↓
4. Server processes iterator_started event
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

```yaml
# Step 1: Worker analyzes loop task
- event: iterator_started
  data:
    iterator_name: "item"
    collection_size: 100
    mode: "async"
    concurrency: 5
    chunk_size: null

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
    total_iterations: 100
    successful: 98
    failed: 2
    results: [...]  # Aggregated results in order
```

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
    connection: main_db
```

**Sink Execution Flow:**
1. Worker executes iteration (HTTP call)
2. Worker executes sink (save to Postgres) **in same job**
3. If sink fails, entire iteration fails (atomic transaction)
4. Worker reports iteration result (success/failed)

**Sink operates as single transaction with iteration - if sink fails, iteration fails.**

## Retry Architecture

### Current (Incorrect) Implementation

```
Worker receives HTTP task with retry config
    ↓
execute_with_retry() wraps HTTP executor
    ↓
Worker retries in-process (while loop)
    ↓
Worker returns final result after N attempts
```

**Problems:**
- Violates distributed computation principle
- No event traceability for retry attempts
- Cannot handle timeouts between retries
- Blocks worker for entire retry sequence
- No server visibility into retry state

### Correct (Event-Driven) Implementation

#### Retry on Error (Failure Retry)

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

#### Retry on Success (Pagination/Polling)

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
      on_error:
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
      on_success:
        while: "{{ response.paging.hasMore }}"
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
    on_success:
      while: "{{ response.paging.hasMore }}"
      max_attempts: 100
      next_call:
        params:
          page: "{{ response.paging.page + 1 }}"
      collect: append
      merge_path: data
  sink:
    tool: postgres
    table: raw_data
    connection: main_db
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
    on_success:
      while: "{{ response.paging.hasMore }}"
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
    on_success:
      while: "{{ response.paging.hasMore }}"
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

## Implementation Components

### 1. Worker Changes

**Remove:**
- `execute_with_retry()` from `noetl/plugin/runtime/execution.py`
- In-process retry loops in `noetl/plugin/runtime/retry.py`
- In-process iteration execution in `noetl/plugin/controller/iterator/executor.py`

**Add:**
- Iterator analysis phase: Count collection, prepare metadata
- Retry metadata in event payloads (attempt_number, retry_config)

### 2. Server Orchestrator Changes

**Add to orchestrator.py:**

```python
async def _process_iterator_started(execution_id: int, event: Dict) -> None:
    """
    Process iterator_started event - enqueue iteration jobs.
    
    Creates N queue entries (one per iteration/batch) with:
    - parent_execution_id linking to loop
    - iteration_index and element/batch data
    """
    pass

async def _process_iteration_completed(execution_id: int, event: Dict) -> None:
    """
    Track iteration completion, check if all done.
    
    When all iterations complete, emit iterator_completed and continue workflow.
    """
    pass

async def _process_retry_eligible_event(execution_id: int, event: Dict) -> None:
    """
    Check if failed/completed action should be retried.
    
    Evaluates retry policies in order (first match wins):
    - Error conditions: Check max_attempts, error matching, backoff
    - Success conditions: Evaluate when condition, apply next_call transforms
    
    If should retry, re-enqueue job with updated config.
    """
    pass

async def _aggregate_retry_results(execution_id: int, parent_event_id: str) -> Dict:
    """
    Aggregate results from retry sequence based on collect strategy.
    
    Strategies:
    - append: Concatenate arrays
    - replace: Use latest result
    - collect: Build array of all results
    """
    pass
```

### 3. Queue Service Changes

**Add to queue/service.py:**

```python
async def enqueue_iteration_jobs(
    parent_execution_id: int,
    iterator_config: Dict,
    collection: List,
    nested_task: Dict
) -> List[int]:
    """
    Enqueue multiple iteration jobs in batch.
    
    Returns list of queue_ids for tracking.
    """
    pass

async def enqueue_retry_job(
    original_queue_id: int,
    task_config: Dict,
    attempt_number: int,
    parent_event_id: str,
    backoff_seconds: int = 0
) -> int:
    """
    Re-enqueue task for retry attempt.
    
    If backoff_seconds > 0, set scheduled_at in future.
    """
    pass
```

### 4. Event Schema Extensions

Add fields to event table (or metadata JSON):

```sql
-- For retry tracking
attempt_number INT DEFAULT 1
parent_event_id BIGINT  -- Links retry to original attempt
retry_sequence_id BIGINT  -- Groups all attempts in sequence

-- For iterator tracking
iteration_index INT  -- Position in collection
total_iterations INT  -- Total expected iterations
```

### 5. State Tracking Tables (Optional)

Consider adding auxiliary tables for tracking:

```sql
-- Track loop execution state
CREATE TABLE noetl.iterator_state (
    execution_id BIGINT PRIMARY KEY,
    total_iterations INT NOT NULL,
    completed_iterations INT DEFAULT 0,
    failed_iterations INT DEFAULT 0,
    status VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Track retry sequence state
CREATE TABLE noetl.retry_state (
    retry_sequence_id BIGINT PRIMARY KEY,
    execution_id BIGINT NOT NULL,
    step_name VARCHAR(255) NOT NULL,
    current_attempt INT DEFAULT 1,
    max_attempts INT NOT NULL,
    last_result JSONB,
    status VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

## Sink Architecture

### Sink as Atomic Transaction

Sink executes **in the same worker job** as the action:

```python
# Worker execution sequence
def execute_job(job):
    # 1. Execute main action
    result = execute_action(job.task_config)
    
    # 2. If action succeeded and sink configured
    if result.status == 'success' and job.task_config.get('sink'):
        try:
            sink_result = execute_sink(job.task_config.sink, result.data)
        except Exception as e:
            # Sink failure = action failure
            result.status = 'error'
            result.error = f"Sink failed: {e}"
    
    # 3. Report final result
    emit_event('action_completed' if result.status == 'success' else 'action_failed', result)
```

### Sink Configuration

Sink can be configured at different levels:

#### Loop-Level Sink (Per-Iteration)
```yaml
- step: process_batch
  tool: python
  code: "def main(item): return transform(item)"
  loop:
    collection: "{{ items }}"
    element: item
  sink:  # Executes once per iteration
    tool: postgres
    table: results
```

#### Retry-Level Sink (Per-Attempt)
```yaml
- step: fetch_pages
  tool: http
  url: "{{ api }}/data"
  retry:
    on_success:
      while: "{{ response.hasMore }}"
  sink:  # Executes once per page
    tool: postgres
    table: raw_pages
    mode: append
```

#### Combined Loop+Retry Sink
```yaml
- step: fetch_all
  tool: http
  url: "{{ endpoint }}/data"
  loop:
    collection: "{{ endpoints }}"
    element: endpoint
  retry:
    on_success:
      while: "{{ response.hasMore }}"
  sink:  # Executes once per (endpoint, page) combination
    tool: postgres
    table: api_data
```

## Benefits of Distributed Architecture

1. **Traceability**: Every iteration and retry is tracked in event log
2. **Observability**: Real-time monitoring of progress
3. **Failure Handling**: Granular retry at iteration level
4. **Resource Efficiency**: Workers don't block for entire loop/retry sequence
5. **Scalability**: Multiple workers can process iterations in parallel
6. **Fault Tolerance**: Worker crash doesn't lose entire loop progress
7. **Debugging**: Can inspect state between iterations/retries
8. **Fairness**: Short tasks don't wait behind long loops

## Metadata and Context Tracking

### Meta Column Utilization

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

**Iterator Completed Events:**
```json
{
  "total_iterations": 100,
  "completed_iterations": 98,
  "success_rate": 0.98,
  "completed_at": "2025-12-06T10:35:00Z"
}
```

### Context Column Tracking

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
Worker executes action with context
    ↓
Worker sanitizes context (_sanitize_context_for_event)
    ↓
Worker emits event via server API (/api/v1/event/emit)
    ↓
Server stores in event.context column
    ↓
Server reads context to reconstruct state
    ↓
Server uses context for retry decisions and next step evaluation
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
    "retry_config": {
      "on_success": {
        "while": "{{ response.paging.hasMore }}",
        "max_attempts": 100
      }
    },
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
    },
    "queue_meta": {
      "queue_id": 456789,
      "worker_id": "worker-1"
    }
  },
  "parent_event_id": "789012",
  "parent_execution_id": 345678
}
```

### Benefits of Metadata and Context Tracking

1. **Complete State Reconstruction**: Server can rebuild execution state from context in events
2. **Retry Decision Making**: Full retry_config and attempt_number available for server logic
3. **Performance Analytics**: Duration, success rates, retry patterns tracked in meta
4. **Debugging and Traceability**: Full execution trail with context snapshots at each step
5. **Distributed Coordination**: Context flows through server API, no direct database access needed
6. **Workflow Continuation**: Next steps can access previous step results via context
7. **Failure Analysis**: Error metadata includes truncated messages, stack trace flags, timestamps

### Implementation Details

**Worker-Side** (`noetl/worker/job_executor.py`):
```python
def _sanitize_context_for_event(self, context: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize execution context for event storage."""
    # Remove sensitive data, limit size, keep execution state
    # Returns safe context for event.context column

def _build_complete_event(...):
    # Add execution context
    if exec_ctx:
        event['context'] = self._sanitize_context_for_event(exec_ctx)
    
    # Add retry/execution metadata
    event['meta'] = {
        'retry': {...},
        'execution': {...}
    }

def _build_error_event(...):
    # Add execution context
    if exec_ctx:
        event['context'] = self._sanitize_context_for_event(exec_ctx)
    
    # Add retry/execution/error metadata
    event['meta'] = {
        'retry': {...},
        'execution': {...},
        'error': {...}
    }
```

**Server-Side** (`noetl/server/api/run/orchestrator.py`):
```python
async def _process_iterator_started(...):
    # Enqueue iteration jobs with metadata
    iteration_meta = {
        'iterator': {
            'parent_execution_id': execution_id,
            'iteration_index': batch['index'],
            'total_iterations': len(batches),
            'iterator_name': iterator_name,
            'mode': mode
        }
    }
    
    await QueueService.enqueue_job(..., metadata=iteration_meta)

async def _process_retry_eligible_event(...):
    # Enqueue retry jobs with metadata
    retry_meta = {
        'retry': {
            'type': 'on_error',
            'attempt_number': attempt_number + 1,
            'max_attempts': max_attempts,
            'parent_event_id': str(event.get('event_id')),
            'backoff_seconds': delay_seconds,
            'scheduled_at': scheduled_time.isoformat()
        }
    }
    
    await QueueService.enqueue_job(..., metadata=retry_meta)
```

## Migration Path

### Phase 1: Add Server-Side Logic (✅ COMPLETED)
- ✅ Add orchestrator methods for iterator/retry processing
- ✅ Add event handlers for iterator_started, iteration_completed, retry events
- ✅ Queue service already supports parent_execution_id, available_at, metadata
- ✅ Event handlers remain backward compatible

### Phase 2: Update Worker (✅ COMPLETED)
- ✅ Remove in-process retry loops from execution.py
- ✅ Convert iterator to job publisher (emit iterator_started event)
- ✅ Update event payloads with retry metadata and execution context
- ✅ Add context sanitization for safe event storage

### Phase 3: Update Playbooks (Optional)
- Existing playbooks work without changes
- New features (backoff strategies, advanced collect) require config updates
- Context-aware next step evaluation uses sanitized context from events

### Phase 4: Add Optimization Features (Future)
- Scheduled retry jobs (backoff in database) - infrastructure ready
- Iterator result streaming (don't hold all results in memory)
- Retry circuit breaker (stop retrying if pattern detected)
- Context-based workflow branching using step result metadata
