# NoETL Retry Testing Guide

**Date**: October 14, 2025  
**Status**: 🔴 **RETRY FUNCTIONALITY NOT WORKING** - Requires Implementation

---

## Problem Summary

NoETL has comprehensive retry configuration syntax and retry logic infrastructure, but **retry is NOT functional** due to implementation gaps:

### Issues Found:

1. **Worker Hard-Codes `retry: False`**
   - Location: `noetl/worker/worker.py:374`
   - Code: `await client.post(f"{self.server_url}/queue/{queue_id}/fail", json={"retry": False})`
   - Impact: All failures are marked as terminal `dead` status, never retried

2. **Retry Policy Not Evaluated**
   - The `RetryPolicy` class exists in `noetl/plugin/tool/retry.py` but is never instantiated
   - Playbook `retry_when` and `stop_when` conditions are never evaluated
   - The `execute_with_retry()` function is not integrated into task execution

3. **Queue Retry Logic Disconnected**
   - Queue system has `attempts` and `max_attempts` columns
   - Simple counter-based retry exists (`attempts < max_attempts`)
   - BUT: No connection to playbook retry configuration

---

## Current Retry Infrastructure

### 1. Retry Configuration (Playbook DSL)

Three configuration formats are supported in playbooks:

```yaml
# Boolean - use defaults
retry: true

# Integer - max attempts only
retry: 5

# Full configuration - MOST DETAILED
retry:
  max_attempts: 3
  initial_delay: 1.0
  backoff_multiplier: 2.0
  max_delay: 60.0
  jitter: true
  retry_when: "{{ error != None or status_code >= 500 }}"
  stop_when: "{{ status_code == 200 }}"
```

### 2. Retry Module (`noetl/plugin/tool/retry.py`)

- **Class**: `RetryPolicy`
  - Parses retry config
  - Evaluates Jinja2 `retry_when` and `stop_when` expressions
  - Calculates exponential backoff delays
  
- **Function**: `execute_with_retry()`
  - Wrapper for task executors with retry logic
  - **NOT CURRENTLY USED** in `execute_task()`

### 3. Queue Retry System (`noetl/server/api/queue/`)

- Columns: `attempts`, `max_attempts`, `status`, `available_at`
- Method: `QueueService.fail_job(queue_id, retry_delay_seconds, retry)`
  - If `retry=False`: Mark as `dead` (terminal failure)
  - If `attempts >= max_attempts`: Mark as `dead`
  - Otherwise: Set `status='queued'` with delayed `available_at`

---

## How Retry SHOULD Work

### Intended Flow:

1. **Worker Executes Task**
   - Task fails (exception or condition not met)
   
2. **Worker Evaluates Retry Policy**
   - Check playbook `retry` configuration
   - Evaluate `retry_when` condition using result context
   - Check `stop_when` condition (overrides retry)
   - Calculate backoff delay
   
3. **Worker Reports Failure to Queue**
   - POST `/queue/{id}/fail` with:
     - `retry: true/false` (based on policy evaluation)
     - `retry_delay_seconds: X` (from backoff calculation)
   
4. **Queue System Reschedules or Terminates**
   - If `retry=true` AND `attempts < max_attempts`: Reschedule
   - Otherwise: Mark as `dead`

---

## Required Fixes

### Fix #1: Integrate RetryPolicy in Worker

**File**: `noetl/worker/worker.py`

**Changes Needed**:

```python
async def _fail_job(self, queue_id: int, retry: bool = True, delay: int = 60) -> None:
    """Mark job failed with retry policy."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{self.server_url}/queue/{queue_id}/fail",
                json={
                    "retry": retry,
                    "retry_delay_seconds": delay
                }
            )
    except Exception:
        logger.debug("Failed to mark job %s failed", queue_id, exc_info=True)


def _execute_job_sync(self, job: Dict[str, Any]) -> None:
    # ... existing setup code ...
    
    try:
        # Execute task
        result = execute_task(...)
        
        # Check if result indicates retry needed
        if action_cfg.get('retry'):
            # Import retry module
            from noetl.plugin.tool.retry import RetryPolicy
            from jinja2 import Environment
            
            # Create Jinja environment
            jinja_env = Environment()
            
            # Parse retry config
            retry_config = action_cfg['retry']
            if isinstance(retry_config, bool) and retry_config:
                retry_config = {}  # Use defaults
            elif isinstance(retry_config, int):
                retry_config = {'max_attempts': retry_config}
            
            # Create policy
            policy = RetryPolicy(retry_config, jinja_env)
            
            # Get current attempt from queue
            attempt = job.get('attempts', 0) + 1
            
            # Evaluate retry policy
            should_retry = policy.should_retry(result, attempt, error=None)
            delay = policy.get_delay(attempt) if should_retry else 60
            
            # Fail with retry policy
            asyncio.run(self._fail_job(queue_id, retry=should_retry, delay=int(delay)))
        else:
            # No retry config, mark terminal failure
            asyncio.run(self._fail_job(queue_id, retry=False))
            
    except Exception as e:
        # Exception case - evaluate retry policy
        if action_cfg.get('retry'):
            # Similar logic but pass exception to should_retry()
            ...
        else:
            asyncio.run(self._fail_job(queue_id, retry=False))
```

### Fix #2: Pass Retry Config to Queue on Enqueue

**File**: `noetl/server/api/broker/service.py`

When enqueuing jobs, extract `max_attempts` from playbook retry config:

```python
# Extract retry config from step/task
retry_config = step_config.get('retry', {})
if isinstance(retry_config, bool):
    max_attempts = 3 if retry_config else 1
elif isinstance(retry_config, int):
    max_attempts = retry_config
elif isinstance(retry_config, dict):
    max_attempts = retry_config.get('max_attempts', 3)
else:
    max_attempts = 3

# Pass to queue
INSERT INTO noetl.queue (..., max_attempts) VALUES (..., max_attempts)
```

### Fix #3: Include Retry Config in Job Context

Ensure `action_cfg` passed to worker includes the original `retry` block so worker can evaluate it.

---

## Testing Strategy

### Test 1: Python Exception Retry (Currently Broken)

**Playbook**: `tests/fixtures/playbooks/retry_test/python_retry_exception.yaml`

```bash
# Register playbook
curl -X POST http://localhost:8083/api/catalog/register \
  -H "Content-Type: application/json" \
  -d @tests/fixtures/playbooks/retry_test/python_retry_exception.yaml

# Execute (should retry on random failures)
curl -X POST http://localhost:8083/api/executions/run \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/retry/python_exception"}'

# Monitor queue
watch -n 1 'curl -s http://localhost:8083/api/queue | jq'

# Check events for retry attempts
curl -s "http://localhost:8083/api/events?execution_id=<ID>" | jq
```

**Expected Behavior**:
- Python code randomly fails 70% of the time
- Should retry up to 5 times
- Events should show multiple `action_started` / `action_error` events
- Queue `attempts` should increment

**Current Behavior**:
- Fails once, marked as `dead`
- No retry happens

### Test 2: HTTP Status Code Retry (Currently Broken)

**Playbook**: `tests/fixtures/playbooks/retry_test/http_retry_status_code.yaml`

```bash
# Execute playbook that retries on 5xx errors
curl -X POST http://localhost:8083/api/executions/run \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/retry/http_status_code"}'
```

**Expected Behavior**:
- Retry when `status_code >= 500`
- Stop after 3 attempts or success

**Current Behavior**:
- No retry happens

### Test 3: HTTP with Stop Condition (Currently Broken)

**Playbook**: `tests/fixtures/playbooks/retry_test/http_retry_with_stop.yaml`

```bash
curl -X POST http://localhost:8083/api/executions/run \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/retry/http_stop_condition"}'
```

**Expected Behavior**:
- Retry while `status_code != 200`
- Stop when `status_code == 200` (overrides retry_when)

**Current Behavior**:
- No retry happens

---

## Manual Testing Without Fixes

Since retry is broken, here's how to simulate retry behavior for testing:

### Option 1: Manual Queue Manipulation

```bash
# 1. Execute a failing playbook
EXEC_ID=$(curl -s -X POST http://localhost:8083/api/executions/run \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/retry/python_exception"}' | jq -r '.execution_id')

# 2. Find the failed job
JOB_ID=$(curl -s "http://localhost:8083/api/queue?status=dead" | jq -r '.items[0].queue_id')

# 3. Manually reschedule it
psql -h localhost -p 54321 -U demo_user -d demo_noetl -c \
  "UPDATE noetl.queue SET status='queued', attempts=attempts-1, available_at=NOW() WHERE queue_id=$JOB_ID"

# 4. Worker will pick it up again
```

### Option 2: Temporarily Patch Worker

Edit `noetl/worker/worker.py` line 374:

```python
# Change from:
await client.post(f"{self.server_url}/queue/{queue_id}/fail", json={"retry": False})

# To:
await client.post(f"{self.server_url}/queue/{queue_id}/fail", json={"retry": True, "retry_delay_seconds": 5})
```

Restart worker and test again. Now ALL failures will retry (not ideal, but proves the mechanism works).

---

## Verification Checklist

After implementing fixes:

- [ ] Python exception retry works (5 attempts)
- [ ] HTTP status code retry works (retries on 5xx)
- [ ] HTTP stop condition works (stops on 200)
- [ ] Exponential backoff visible in `available_at` timestamps
- [ ] `attempts` counter increments in queue table
- [ ] Multiple `action_error` events logged
- [ ] Final success after N retries recorded
- [ ] Max attempts reached → `dead` status
- [ ] `stop_when` condition honored (overrides retry)

---

## Implementation Priority

1. **HIGH**: Fix worker `_fail_job()` to accept retry parameters
2. **HIGH**: Add retry policy evaluation in `_execute_job_sync()`
3. **MEDIUM**: Pass retry config to queue on enqueue
4. **LOW**: Add retry metrics/observability (attempts, delays)

---

## Related Files

- **Retry Logic**: `noetl/plugin/tool/retry.py` (RetryPolicy, execute_with_retry)
- **Worker Execution**: `noetl/worker/worker.py` (_execute_job_sync, _fail_job)
- **Queue Service**: `noetl/server/api/queue/service.py` (fail_job)
- **Test Playbooks**: `tests/fixtures/playbooks/retry_test/`
- **Documentation**: `tests/fixtures/playbooks/retry_test/README.md`

---

## Conclusion

NoETL has well-designed retry infrastructure but it's **not connected**. The fixes are straightforward:

1. Change worker to evaluate retry policies
2. Pass retry decision to queue service
3. Let queue system handle rescheduling with backoff

Once implemented, the existing test playbooks should work correctly.
