# Event-Driven Retry Architecture

## Overview

The retry mechanism must be integrated into NoETL's event-driven architecture where the server orchestrates all retry logic through the event queue system. This ensures proper state management, observability, and distributed execution support.

## Current Architecture

### Event-Queue Flow
1. **Worker** executes task → reports `action_completed` or `action_error` event
2. **Server** receives event → stores in `noetl.event` table
3. **Server** triggers broker evaluation → determines next steps
4. **Server** enqueues next tasks → writes to `noetl.queue` table
5. **Worker** polls queue → leases job → executes → reports event (cycle repeats)

### Key Tables
- **noetl.event**: Event log with execution history and results
- **noetl.queue**: Job queue with `attempts`, `max_attempts`, `status` columns
- **noetl.workload**: Execution context and playbook configuration

## Retry Architecture Design

### Principles
1. **Server-Side Orchestration**: Retry decisions made by server, not worker
2. **Event-Driven**: Each retry attempt creates event records for observability
3. **Queue-Based**: Retries go through normal queue mechanism
4. **Stateless Workers**: Workers execute tasks without retry awareness
5. **Playbook Configuration**: Retry policy defined in playbook YAML

### Retry Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Retry Execution Cycle                         │
└─────────────────────────────────────────────────────────────────┘

 1. Worker Executes Task
    ├─ Success → action_completed event
    └─ Failure → action_error event

 2. Server Receives Event (EventService.emit)
    ├─ Store event in noetl.event
    ├─ Update queue.attempts++
    └─ Trigger broker evaluation

 3. Broker Evaluates Retry (evaluate_broker_for_execution)
    ├─ Check if retry configured for this step
    ├─ Load retry policy from playbook
    ├─ Evaluate retry_when condition using event result
    ├─ Check attempts < max_attempts
    └─ Decide: retry or fail

 4a. Retry Decision: YES
    ├─ Calculate backoff delay
    ├─ Create retry event (step_retry)
    ├─ Re-enqueue task with available_at = now + delay
    └─ Update queue.status = 'queued'

 4b. Retry Decision: NO
    ├─ Create failure event (step_failed)
    ├─ Update queue.status = 'dead'
    └─ Continue workflow evaluation

 5. Worker Polls Queue
    ├─ Lease job where available_at <= now
    ├─ Execute task (unaware it's a retry)
    └─ Report result event (back to step 1)
```

### Database Schema Updates

#### Queue Table Enhancement
```sql
ALTER TABLE noetl.queue ADD COLUMN IF NOT EXISTS retry_config JSONB;
ALTER TABLE noetl.queue ADD COLUMN IF NOT EXISTS last_error TEXT;
ALTER TABLE noetl.queue ADD COLUMN IF NOT EXISTS retry_delay_seconds FLOAT;
```

#### Event Types for Retry
- `step_retry`: Retry attempt initiated
- `step_retry_exhausted`: All retry attempts exhausted
- `step_failed_terminal`: Terminal failure (no retry)

### Implementation Components

#### 1. Retry Policy Evaluator (`noetl/server/api/event/processing/retry.py`)
```python
class RetryEvaluator:
    """Evaluates retry decisions based on event results and playbook retry config."""
    
    async def should_retry(
        self,
        execution_id: str,
        node_id: str,
        event: Dict[str, Any],
        retry_config: Dict[str, Any],
        current_attempt: int
    ) -> Tuple[bool, Optional[float]]:
        """
        Determine if task should be retried.
        
        Returns:
            (should_retry: bool, delay_seconds: Optional[float])
        """
        # Check max attempts
        if current_attempt >= retry_config.get('max_attempts', 3):
            return False, None
            
        # Evaluate retry_when condition using Jinja2
        if 'retry_when' in retry_config:
            should_retry = await self._evaluate_condition(
                retry_config['retry_when'],
                event,
                execution_id
            )
            if not should_retry:
                return False, None
        
        # Evaluate stop_when condition
        if 'stop_when' in retry_config:
            should_stop = await self._evaluate_condition(
                retry_config['stop_when'],
                event,
                execution_id
            )
            if should_stop:
                return False, None
        
        # Calculate backoff delay
        delay = self._calculate_delay(retry_config, current_attempt)
        return True, delay
```

#### 2. Broker Retry Integration (`noetl/server/api/event/processing/broker.py`)
```python
async def _handle_action_completion(execution_id: str, event: Dict[str, Any]):
    """Handle action completion or error events with retry logic."""
    
    node_id = event.get('node_id')
    event_type = event.get('event_type')
    
    # Check if this is a failure/error that might need retry
    if event_type in ['action_error', 'action_failed']:
        # Get current queue entry
        queue_entry = await _get_queue_entry(execution_id, node_id)
        if not queue_entry:
            return
            
        # Get retry config from playbook
        retry_config = await _get_retry_config(execution_id, node_id)
        if not retry_config:
            # No retry configured, handle as terminal failure
            await _handle_terminal_failure(execution_id, node_id, event)
            return
        
        # Evaluate retry decision
        from .retry import RetryEvaluator
        evaluator = RetryEvaluator()
        should_retry, delay = await evaluator.should_retry(
            execution_id,
            node_id,
            event,
            retry_config,
            queue_entry['attempts']
        )
        
        if should_retry:
            await _enqueue_retry(execution_id, node_id, event, delay, queue_entry)
        else:
            await _handle_retry_exhausted(execution_id, node_id, event, queue_entry)
    else:
        # Success case - continue normal workflow
        await _advance_workflow(execution_id, event)
```

#### 3. Retry Enqueueing (`noetl/server/api/event/processing/retry.py`)
```python
async def enqueue_retry(
    execution_id: str,
    node_id: str,
    event: Dict[str, Any],
    delay_seconds: float,
    queue_entry: Dict[str, Any]
):
    """Re-enqueue a failed task for retry."""
    
    from datetime import datetime, timedelta
    import asyncio
    from noetl.core.common import get_async_db_connection
    
    async with get_async_db_connection() as conn:
        async with conn.cursor() as cur:
            # Calculate available_at with backoff delay
            available_at = datetime.utcnow() + timedelta(seconds=delay_seconds)
            
            # Update existing queue entry
            await cur.execute("""
                UPDATE noetl.queue
                SET status = 'queued',
                    attempts = attempts + 1,
                    available_at = %s,
                    retry_delay_seconds = %s,
                    last_error = %s,
                    worker_id = NULL,
                    lease_until = NULL,
                    updated_at = NOW()
                WHERE execution_id = %s AND node_id = %s
            """, (
                available_at,
                delay_seconds,
                event.get('error'),
                execution_id,
                node_id
            ))
            
            # Emit retry event
            from noetl.server.api.event.service import get_event_service
            service = get_event_service()
            await service.emit({
                'execution_id': execution_id,
                'event_type': 'step_retry',
                'status': 'PENDING',
                'node_id': node_id,
                'node_name': queue_entry.get('node_name'),
                'node_type': queue_entry.get('node_type'),
                'context': {
                    'attempt': queue_entry['attempts'] + 1,
                    'max_attempts': queue_entry['max_attempts'],
                    'delay_seconds': delay_seconds,
                    'last_error': event.get('error')
                }
            })
            
            await conn.commit()
```

#### 4. Worker Changes (Minimal)
```python
# Workers remain mostly unchanged
# They only need to:
# 1. Report attempt number in events
# 2. Include retry metadata in action_started event

def _execute_job_sync(self, job: Dict[str, Any]) -> None:
    """Execute job with retry metadata."""
    
    attempt_number = job.get('attempts', 0) + 1
    max_attempts = job.get('max_attempts', 1)
    
    start_event = {
        "execution_id": execution_id,
        "event_type": "action_started",
        "status": "STARTED",
        "node_id": node_id,
        "context": {
            "work": context,
            "task": action_cfg,
            "retry": {
                "attempt": attempt_number,
                "max_attempts": max_attempts,
                "is_retry": attempt_number > 1
            }
        }
    }
    report_event(start_event, self.server_url)
    
    # Execute task normally...
```

### Playbook Configuration

#### Full Retry Configuration
```yaml
workflow:
  - step: fetch_data
    type: http
    url: https://api.example.com/data
    retry:
      max_attempts: 5
      initial_delay: 1.0
      backoff_multiplier: 2.0
      max_delay: 60.0
      jitter: true
      retry_when: "{{ status_code >= 500 or error != None }}"
      stop_when: "{{ status_code == 200 and success == True }}"
    next:
      - step: process_data
```

#### Simplified Retry Configuration
```yaml
# Boolean (use defaults)
retry: true

# Integer (max attempts only)
retry: 3

# Minimal config
retry:
  max_attempts: 5
  retry_when: "{{ status_code >= 500 }}"
```

### Retry Context Variables

When evaluating retry conditions, the following variables are available:
- `result`: Full task result dictionary
- `status_code`: HTTP status code (for HTTP tasks)
- `error`: Error message if task failed
- `success`: Boolean success flag
- `data`: Task result data
- `attempt`: Current attempt number
- `execution_id`: Current execution ID
- `node_id`: Current step/node ID

### Event Timeline Example

For a task with retry configured:

```
1. action_started (attempt=1)
2. action_error (attempt=1, error="503 Service Unavailable")
3. step_retry (attempt=1, delay=1.0s)
   [wait 1 second]
4. action_started (attempt=2)
5. action_error (attempt=2, error="503 Service Unavailable")
6. step_retry (attempt=2, delay=2.0s)
   [wait 2 seconds]
7. action_started (attempt=3)
8. action_completed (attempt=3, success=True)
9. step_completed
```

If all attempts fail:
```
1-6. [same as above]
7. action_started (attempt=3)
8. action_error (attempt=3, error="503 Service Unavailable")
9. step_retry_exhausted (attempts=3, max_attempts=3)
10. step_failed_terminal
11. execution_failed
```

### Migration Steps

1. **Add retry columns to queue table**
2. **Create RetryEvaluator class** in `noetl/server/api/event/processing/retry.py`
3. **Update broker** to check for retry config and evaluate retry decisions
4. **Add retry event handlers** in EventService
5. **Update worker** to include retry metadata in events
6. **Remove local retry logic** from `noetl/plugin/tool/retry.py` and `execution.py`
7. **Update playbook schema** to include retry configuration
8. **Create retry test playbooks** with various retry scenarios
9. **Add retry monitoring** to observability stack

### Benefits

1. **Full Observability**: All retry attempts visible in event log
2. **Distributed Execution**: Multiple workers can handle retries
3. **Queue Management**: Retry delays handled by PostgreSQL queue
4. **State Persistence**: Retry state survives server restarts
5. **Debugging**: Complete audit trail of all retry attempts
6. **Metrics**: Retry success/failure rates tracked in events
7. **Backpressure**: Queue-based retry prevents thundering herd

### Limitations

1. **Server Dependency**: Retry decisions require server-side evaluation
2. **Delay Accuracy**: Retry delays depend on worker polling interval
3. **Queue Overhead**: Each retry creates queue and event records
4. **Jinja2 Evaluation**: Retry conditions evaluated server-side only

### Testing Strategy

1. **Unit Tests**: RetryEvaluator condition evaluation
2. **Integration Tests**: Full retry cycle through queue
3. **Failure Tests**: Network failures, database errors, timeouts
4. **Performance Tests**: High retry volume handling
5. **Observability Tests**: Event timeline verification
