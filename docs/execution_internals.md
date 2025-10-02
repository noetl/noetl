# NoETL Execution Internals

## Overview

This document provides a detailed technical overview of NoETL's internal execution logic, covering the complete lifecycle from job queuing to result processing. The system follows a distributed, event-driven architecture where the server coordinates execution while workers perform the actual tasks.

## Architecture Components

### Core Components
- **Server**: FastAPI-based coordinator running on port 8082
- **Workers**: Distributed task processors (CPU/GPU pools)
- **Database**: PostgreSQL with `noetl` schema
- **Queue System**: Task queue in `noetl.queue` table
- **Event System**: Event sourcing via `noetl.event_log` table
- **Broker**: Workflow orchestration engine

### Key Tables
- `noetl.queue`: Task queue for worker coordination
- `noetl.event_log`: Event sourcing and audit trail
- `noetl.workload`: Execution context and parameters
- `noetl.runtime`: Worker pool registration

## Execution Flow Overview

```
Client Request → Server → Broker Evaluation → Queue Jobs → Workers → Events → Broker → Complete
```

## Detailed Execution Process

### 1. Execution Initiation

**Entry Point**: `/api/executions/execute`
**File**: `noetl/server/api/execution.py`

When a client submits a playbook for execution:

1. **Request Processing**:
   ```python
   # Generate snowflake execution ID
   execution_id = get_snowflake_id_str()
   
   # Store workload context
   workload_data = {
       "execution_id": execution_id,
       "playbook_path": playbook_id,
       "context": input_context,
       "version": playbook_version
   }
   ```

2. **Initial Event**:
   ```sql
   INSERT INTO noetl.event_log (
       execution_id, event_type, status, node_name, 
       node_type, context, metadata, timestamp
   ) VALUES (
       %s, 'execution_start', 'running', %s, 
       'playbook', %s, %s, NOW()
   )
   ```

3. **Broker Trigger**:
   ```python
   # Trigger initial broker evaluation
   await evaluate_broker_for_execution(execution_id)
   ```

### 2. Broker Evaluation Process

**File**: `noetl/server/api/event/processing.py` - `evaluate_broker_for_execution()`

The broker is the core orchestration engine that:

#### 2.1 Context Building
```python
# Build execution context from event history
async with get_async_db_connection() as conn:
    async with conn.cursor() as cur:
        # Get workload context
        await cur.execute("SELECT data FROM noetl.workload WHERE execution_id = %s", (execution_id,))
        
        # Get results from completed actions
        await cur.execute("""
            SELECT node_name, result 
            FROM noetl.event_log 
            WHERE execution_id = %s AND event_type = 'action_completed'
        """, (execution_id,))
```

#### 2.2 Playbook Parsing
```python
# Fetch playbook definition
catalog = get_catalog_service()
entry = await catalog.fetch_entry(playbook_path, playbook_version)

# Parse YAML content
pb = yaml.safe_load(entry.get('content') or '')
steps = pb.get('steps') or pb.get('workflow') or []
```

#### 2.3 Step Progression Logic
```python
# Determine next actionable step
while idx < len(steps):
    step = steps[idx]
    
    # Check if step already completed
    completed = await check_step_completion(execution_id, step_name)
    if completed:
        idx += 1
        continue
        
    # Evaluate step conditions (when/pass)
    if not evaluate_step_conditions(step, context):
        # Emit skip event
        await emit_skip_event(execution_id, step_name)
        idx += 1
        continue
        
    # Found actionable step - enqueue it
    break
```

### 3. Job Queuing Process

**File**: `noetl/server/api/event/processing.py` - `evaluate_broker_for_execution()`

When the broker finds an actionable step:

#### 3.1 Task Configuration
```python
# Build task configuration
task_config = {
    "name": step_name,
    "type": step.get("type"),
    "action": step.get("action"),
    **step  # Include all step properties
}

# Encode multiline code/commands to base64
encoded_task = encode_task_for_queue(task_config)
```

#### 3.2 Queue Insertion
```sql
INSERT INTO noetl.queue (
    execution_id, node_id, action, context, 
    status, priority, attempts, max_attempts,
    available_at, created_at, updated_at
) VALUES (
    %s, %s, %s, %s,
    'queued', %s, 0, 5,
    NOW(), NOW(), NOW()
)
```

**Queue Table Schema**:
```sql
CREATE TABLE noetl.queue (
    id             BIGSERIAL PRIMARY KEY,
    execution_id   BIGINT NOT NULL,
    node_id        VARCHAR NOT NULL,           -- Unique step identifier
    action         TEXT NOT NULL,              -- JSON task configuration
    context        JSONB,                      -- Execution context
    status         TEXT DEFAULT 'queued',      -- queued|leased|done
    priority       INTEGER DEFAULT 0,
    attempts       INTEGER DEFAULT 0,
    max_attempts   INTEGER DEFAULT 5,
    available_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    lease_until    TIMESTAMP WITH TIME ZONE,
    worker_id      TEXT,
    last_heartbeat TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at     TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at     TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### 4. Worker Processing

**File**: `noetl/worker.py` - `QueueWorker` class

#### 4.1 Job Leasing
Workers continuously poll for available jobs:

```python
async def _lease_job(self, lease_seconds: int = 60) -> Optional[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(
            f"{self.server_url}/queue/lease",
            json={"worker_id": self.worker_id, "lease_seconds": lease_seconds}
        )
```

**Server-side Leasing Logic** (`noetl/server/api/queue.py`):
```sql
WITH cte AS (
  SELECT id FROM noetl.queue
  WHERE status='queued' AND (available_at IS NULL OR available_at <= NOW())
  ORDER BY priority DESC, id
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
UPDATE noetl.queue q
SET status='leased',
    worker_id=%s,
    lease_until=NOW() + (%s || ' seconds')::interval,
    last_heartbeat=NOW(),
    attempts = q.attempts + 1
FROM cte
WHERE q.id = cte.id
RETURNING q.*;
```

#### 4.2 Context Rendering
Workers request server-side context rendering:

```python
# Request context rendering from server
render_response = await client.post(
    f"{self.server_url}/context/render",
    json={
        "execution_id": execution_id,
        "template": raw_context,
        "strict": False
    }
)
context = render_response.json().get('result', {})
```

#### 4.3 Task Execution
```python
def _execute_job_sync(self, job: Dict[str, Any]) -> None:
    # Parse job details
    action_cfg = job.get("action")
    execution_id = job.get("execution_id")
    node_id = job.get("node_id")
    
    # Emit start event
    start_event = {
        "execution_id": execution_id,
        "event_type": "action_started",
        "status": "RUNNING",
        "node_id": node_id,
        "node_name": task_name,
        "node_type": "task"
    }
    report_event(start_event, self.server_url)
    
    # Execute actual task
    from noetl.job import execute_task
    result = execute_task(action_cfg, context)
    
    # Emit completion event
    complete_event = {
        "execution_id": execution_id,
        "event_type": "action_completed",
        "status": "COMPLETED",
        "node_id": node_id,
        "result": result
    }
    report_event(complete_event, self.server_url)
```

### 5. Action Module Dispatch

**File**: `noetl/job/__init__.py` - `execute_task()`

The action dispatcher routes tasks to specific handlers:

```python
def execute_task(task_config: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    task_type = task_config.get('type', '').lower()
    
    if task_type == 'http':
        from noetl.job.http import execute_http_task
        return execute_http_task(task_config, context)
    elif task_type == 'python':
        from noetl.job.python import execute_python_task
        return execute_python_task(task_config, context)
    elif task_type == 'postgres':
        from noetl.job.postgres import execute_postgres_task
        return execute_postgres_task(task_config, context)
    # ... other task types
```

**Action Modules**:
- `noetl/job/http.py`: HTTP requests and API calls
- `noetl/job/python.py`: Python code execution
- `noetl/job/postgres.py`: PostgreSQL operations
- `noetl/job/duckdb.py`: DuckDB operations
- `noetl/job/secrets.py`: Secret management
- `noetl/job/workbook.py`: Nested playbook execution

### 6. Event Publishing

**File**: `noetl/job/action.py` - `report_event()`

Workers publish events back to the server:

```python
def report_event(event_data: Dict[str, Any], server_url: str) -> None:
    try:
        response = requests.post(
            f"{server_url}/events",
            json=event_data,
            timeout=30
        )
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to report event: {e}")
```

### 7. Event Processing

**File**: `noetl/server/api/event/service.py` - `EventService.emit()`

The server processes incoming events:

#### 7.1 Event Storage
```python
async def emit(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
    # Generate event ID
    event_id = event_data.get("event_id", get_snowflake_id_str())
    
    # Store in event_log
    async with get_async_db_connection() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("""
                INSERT INTO noetl.event_log (
                    event_id, execution_id, event_type, status,
                    node_id, node_name, node_type, context, result,
                    metadata, timestamp
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """, (event_id, execution_id, event_type, status, 
                  node_id, node_name, node_type, context_json, 
                  result_json, metadata_json))
```

#### 7.2 Completion Handling
```python
# Check for execution completion
if event_type in ['execution_completed', 'execution_complete']:
    # Handle child execution completion
    if parent_execution_id:
        # Extract child result and emit to parent
        await self.emit({
            'event_type': 'action_completed',
            'execution_id': parent_execution_id,
            'node_id': parent_step,
            'result': child_result
        })
        
        # Check distributed loop completion
        await _check_distributed_loop_completion(parent_execution_id, parent_step)
```

#### 7.3 Broker Re-evaluation Trigger
```python
# Trigger broker evaluation for key events
if event_type.lower() in {"execution_start", "action_completed", "action_error", 
                         "loop_completed", "result"}:
    asyncio.create_task(evaluate_broker_for_execution(execution_id))
```

### 8. Job Completion

**File**: `noetl/server/api/queue.py` - `complete_job()`

Workers mark jobs as complete:

```sql
UPDATE noetl.queue 
SET status='done', lease_until=NULL 
WHERE id = %s
```

### 9. Loop Handling

NoETL iteration is modeled via iterator steps.

#### 9.1 Distributed Iterators
For iterator steps that delegate to child playbooks (nested playbook as the iterator.task):

```python
# Create child executions for each loop item
for idx, item in enumerate(items):
    child_execution_id = get_snowflake_id_str()
    
    # Store child workload
    child_workload = {
        **workload,
        element: item,
        '_loop': {
            'loop_id': f"{execution_id}:{step_name}",
            'current_index': idx,
            'current_item': item
        }
    }
    
    # Emit child execution
    await event_service.emit({
        'event_type': 'execution_start',
        'execution_id': child_execution_id,
        'meta': {
            'parent_execution_id': execution_id,
            'parent_step': step_name
        }
    })
```

#### 9.2 Inline Iterators
For iterator steps that run a nested task directly:

```python
# Queue multiple tasks for the same step
for idx, item in enumerate(items):
    task_context = {**context, element: item}
    
    await enqueue_job({
        'execution_id': execution_id,
        'node_id': f"{execution_id}-step-{step_idx}-iter-{idx}",
        'action': task_config,
        'context': task_context
    })
```

### 10. Execution Completion

#### 10.1 Step Completion Detection
The broker determines completion by checking:

```sql
-- Count expected vs completed items
SELECT COUNT(*) as expected 
FROM noetl.queue 
WHERE execution_id = %s AND node_id LIKE %s

SELECT COUNT(*) as completed
FROM noetl.event_log 
WHERE execution_id = %s AND node_name = %s 
AND event_type = 'action_completed'
```

#### 10.2 Main Execution Completion
When `idx >= len(steps)` in broker evaluation:

```python
if idx is None or idx >= len(steps):
    # Check if this is a main execution (no parent)
    if not parent_execution_id:
        # Emit execution_completed for main execution
        await event_service.emit({
            "execution_id": execution_id,
            "event_type": "execution_completed",
            "status": "completed",
            "node_name": playbook_path,
            "node_type": "playbook",
            "result": final_result
        })
```

## Event Types and Their Meanings

### Core Event Types
- `execution_start`: Execution initiated
- `action_started`: Task began processing
- `action_completed`: Task finished successfully
- `action_error`: Task failed
- `execution_completed`: Execution finished
- `loop_started`: Loop iteration began
- `loop_completed`: Loop finished
- `result`: Final step result (for aggregation)

### Event Flow Example
```
execution_start → action_started → action_completed → action_started → ... → execution_completed
```

## Error Handling and Reliability

### Lease Expiration
- Jobs have `lease_until` timestamps
- Expired leases can be reclaimed: `UPDATE noetl.queue SET status='queued', worker_id=NULL WHERE lease_until < NOW()`

### Retry Logic
- Jobs track `attempts` vs `max_attempts`
- Failed jobs can be retried or marked as `dead`

### Worker Heartbeats
- Workers send heartbeats via `/api/queue/{job_id}/heartbeat`
- Extends lease and updates `last_heartbeat`

### Deadlock Prevention
- Queue leasing uses `FOR UPDATE SKIP LOCKED`
- Retry logic with exponential backoff for database conflicts

## Performance Considerations

### Indexing
Key indexes on `noetl.queue`:
```sql
CREATE INDEX idx_queue_status_available ON noetl.queue (status, available_at, priority DESC, id);
CREATE INDEX idx_queue_exec ON noetl.queue (execution_id);
CREATE INDEX idx_queue_worker ON noetl.queue (worker_id);
```

### Scaling
- Horizontal: Add more worker instances
- Vertical: Increase worker pool sizes
- Database: Connection pooling and read replicas

## Monitoring and Observability

### Key Metrics
- Queue depth: `SELECT COUNT(*) FROM noetl.queue WHERE status = 'queued'`
- Active jobs: `SELECT COUNT(*) FROM noetl.queue WHERE status = 'leased'`
- Worker utilization: `SELECT worker_id, COUNT(*) FROM noetl.queue WHERE status = 'leased' GROUP BY worker_id`

### Health Checks
- Server: `GET /health`
- Workers: Heartbeat timestamps
- Database: Connection status

## Troubleshooting

### Common Issues
1. **Stuck Executions**: Check for expired leases in queue
2. **Worker Disconnection**: Check worker logs and heartbeats
3. **Broker Loops**: Check for circular step dependencies
4. **Memory Leaks**: Monitor event_log growth

### Debug Commands
```sql
-- Find stuck executions
SELECT execution_id FROM noetl.event_log 
WHERE event_type = 'execution_start' 
AND execution_id NOT IN (
    SELECT execution_id FROM noetl.event_log 
    WHERE event_type = 'execution_completed'
);

-- Reset expired leases
UPDATE noetl.queue 
SET status='queued', worker_id=NULL, lease_until=NULL 
WHERE status='leased' AND lease_until < NOW();
```

## Configuration

### Environment Variables
- `NOETL_SERVER_URL`: Worker server connection
- `NOETL_WORKER_ID`: Unique worker identifier
- `NOETL_DB_URL`: Database connection string
- `NOETL_QUEUE_POLL_INTERVAL`: Worker polling frequency

### Tuning Parameters
- Queue lease duration (default: 60 seconds)
- Max retry attempts (default: 5)
- Worker pool sizes (CPU/GPU)
- Database connection limits

This document provides a comprehensive view of NoETL's execution internals, enabling developers to understand, debug, and extend the system effectively.
