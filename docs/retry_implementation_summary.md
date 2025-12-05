# Event-Driven Retry Implementation - Summary

## Implementation Complete

The retry mechanism has been successfully integrated into NoETL's event-driven architecture where the server orchestrates all retry logic through the event queue system.

## Architecture Overview

### Key Components

1. **Retry Evaluator** (`noetl/server/api/event/processing/retry.py`)
   - Evaluates retry conditions based on event results
   - Calculates exponential backoff delays
   - Supports Jinja2 expression-based retry conditions

2. **Action Event Handler** (`noetl/server/api/event/control/action.py`)
   - Intercepts action_error and action_failed events
   - Retrieves retry configuration from playbook
   - Decides whether to retry or fail terminally
   - Re-enqueues tasks with backoff delay

3. **Worker Integration** (`noetl/worker/worker.py`)
   - Reports retry metadata in action_started events
   - Includes attempt number and max_attempts
   - Workers remain stateless - no retry logic in worker

4. **Event Dispatcher** (`noetl/server/api/event/control/dispatcher.py`)
   - Routes events to appropriate handlers (unchanged)
   - Action events go to action handler which now includes retry

## Execution Flow

```
1. Worker executes task
   ├─ Reports action_started with retry metadata
   └─ Reports action_completed or action_error

2. Server receives event (EventService.emit)
   ├─ Stores event in noetl.event table
   └─ Routes to action handler via dispatcher

3. Action Handler (action.py)
   ├─ Checks if event is action_error/action_failed
   ├─ If error:
   │  ├─ Get queue entry for execution/node
   │  ├─ Get retry config from playbook
   │  ├─ Evaluate retry condition
   │  └─ Decision:
   │     ├─ YES → Re-enqueue with backoff delay
   │     └─ NO → Mark as terminal failure
   └─ Trigger broker to advance workflow

4. Broker evaluation (broker.py)
   ├─ Analyzes event log
   ├─ Determines next steps
   └─ Continues workflow

5. Worker polls queue
   ├─ Leases job (if available_at <= now)
   ├─ Executes task (unaware it's a retry)
   └─ Reports result (cycle repeats)
```

## Event Timeline

For a task with retry configured that fails twice then succeeds:

```
Event Log:
1. action_started (attempt=1, is_retry=false)
2. action_error (error="503 Service Unavailable")
3. step_retry (attempt=1, delay=1.0s, available_at=T+1s)
   [Queue: status=queued, attempts=1, available_at=T+1s]
   [Worker: waits for available_at]
4. action_started (attempt=2, is_retry=true)
5. action_error (error="503 Service Unavailable")
6. step_retry (attempt=2, delay=2.0s, available_at=T+3s)
   [Queue: status=queued, attempts=2, available_at=T+3s]
   [Worker: waits for available_at]
7. action_started (attempt=3, is_retry=true)
8. action_completed (success=true)
9. [Broker advances workflow to next step]
```

For retry exhausted:

```
1-6. [Same as above]
7. action_started (attempt=3, is_retry=true)
8. action_error (error="503 Service Unavailable")
9. step_retry_exhausted (attempts=3, max_attempts=3)
10. step_failed_terminal
    [Queue: status=dead]
11. execution_failed
```

## Database Schema

The `noetl.queue` table already has the necessary columns:
- `attempts`: Current number of attempts (incremented on each retry)
- `max_attempts`: Maximum retry attempts configured
- `available_at`: Timestamp when job becomes available (used for backoff delay)
- `status`: Queue status (queued/leased/completed/dead)

## Configuration

### Playbook YAML

```yaml
workflow:
  - step: fetch_api_data
    tool: http
    url: https://api.example.com/data
    retry:
      max_attempts: 5
      initial_delay: 1.0
      backoff_multiplier: 2.0
      max_delay: 60.0
      jitter: true
      retry_when: "{{ status_code >= 500 or error != None }}"
      stop_when: "{{ status_code == 200 }}"
    next:
      - step: process_data
```

### Simplified Formats

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

## Retry Conditions

Available variables in Jinja2 expressions:
- `result`: Complete task result dictionary
- `response`: Alias for result (HTTP compatibility)
- `status_code`: HTTP status code
- `error`: Error message if failed
- `success`: Boolean success flag
- `data`: Task result data
- `attempt`: Current attempt number
- `execution_id`: Execution ID
- `node_id`: Step/node ID
- `event_type`: Event type
- `status`: Event status

### Example Conditions

```yaml
# Retry on 5xx errors
retry_when: "{{ status_code >= 500 and status_code < 600 }}"

# Retry on specific errors
retry_when: "{{ 'timeout' in (error|lower) or 'connection' in (error|lower) }}"

# Retry with attempt limit
retry_when: "{{ attempt <= 3 and status_code != 200 }}"

# Stop on success
stop_when: "{{ success == True and status_code == 200 }}"
```

## Implementation Files

### Modified Files

1. **noetl/server/api/event/control/action.py** (121 lines)
   - Added `_handle_action_error_with_retry()` function
   - Added `_get_queue_entry()` helper
   - Integrated retry evaluation into action event handling

2. **noetl/worker/worker.py** (Line ~560)
   - Added retry metadata to action_started events
   - Includes attempt number, max_attempts, is_retry flag

3. **noetl/plugin/tool/execution.py** (Reverted)
   - Removed local retry logic wrapper
   - Workers execute tasks without retry awareness

### New Files

1. **noetl/server/api/event/processing/retry.py** (397 lines)
   - `RetryEvaluator` class for condition evaluation
   - `enqueue_retry()` function to re-enqueue with backoff
   - `handle_retry_exhausted()` for terminal failures
   - `get_retry_config_for_step()` to extract config from playbook

2. **docs/retry_event_driven_architecture.md** (Complete architecture documentation)

### Documentation

1. **docs/retry_event_driven_architecture.md**
   - Complete architecture overview
   - Flow diagrams
   - Configuration examples
   - Event timeline examples

2. **tests/fixtures/playbooks/retry_test/README.md**
   - Test playbook documentation
   - Usage examples
   - Best practices

## Test Playbooks

All test playbooks in `tests/fixtures/playbooks/retry_test/` are ready:
- `http_retry_status_code.yaml` - HTTP retry on 5xx status codes
- `http_retry_with_stop.yaml` - HTTP with stop condition
- `python_retry_exception.yaml` - Python exception retry
- `duckdb_retry_query.yaml` - DuckDB query retry
- `retry_simple_config.yaml` - All configuration formats

## Benefits

1. **Full Observability**: All retry attempts recorded in event log
2. **Distributed Execution**: Any worker can handle retries
3. **State Persistence**: Retry state survives server restarts
4. **Queue Management**: PostgreSQL handles retry delays via available_at
5. **Audit Trail**: Complete history of all retry attempts
6. **Metrics Ready**: Retry success/failure rates in events
7. **Backpressure**: Queue-based retry prevents thundering herd
8. **Server Orchestration**: Centralized retry logic for consistency

## Testing

Run retry tests:

```bash
# Register all retry test playbooks
task playbook:local:register-retry-tests

# Run individual tests
task playbook:local:execute:retry-http-status
task playbook:local:execute:retry-python-exception

# Run all retry tests
task test:local:retry-all
```

## Next Steps

1. **Test in Dev Environment**
   - Deploy to kind cluster
   - Execute retry test playbooks
   - Verify event log shows retry attempts

2. **Monitor Retry Behavior**
   - Check Grafana dashboards for retry metrics
   - Validate backoff delay timing
   - Confirm queue state transitions

3. **Production Readiness**
   - Add retry metrics to observability stack
   - Create alerts for high retry rates
   - Document operational procedures

## Migration Notes

- Old local retry logic in `noetl/plugin/tool/retry.py` is preserved but unused
- Can be removed after testing confirms event-driven retry works correctly
- No breaking changes to playbook format
- Existing playbooks without retry continue to work normally
