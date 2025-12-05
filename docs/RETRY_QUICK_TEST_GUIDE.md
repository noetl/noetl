# NoETL Retry Testing Guide

## Quick Start - Reset and Test Retry

### 1. Reset NoETL (Restart Server and Worker)

```bash
task noetl:local:start
```

This command will:
- Kill any existing server/worker processes
- Start fresh server on port 8083
- Start fresh worker
- Clear old logs and state

### 2. Register Retry Test Playbook

```bash
# Register the always-fail test playbook
.venv/bin/python -m noetl.main catalog register test_retry_always_fail_events.yaml \
  --host localhost --port 8083
```

### 3. Execute Retry Test

```bash
# Execute the playbook
curl -X POST http://localhost:8083/api/executions/run \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/retry/always_fail_events"}' | python3 -m json.tool
```

### 4. Monitor Retry Attempts

#### Real-time Queue Monitoring
```bash
# Watch retry status changes
watch -n 1 'curl -s http://localhost:8083/api/queue | \
  python3 -m json.tool | grep -E "status|attempts"'
```

#### Check Specific Execution
```bash
# Replace EXEC_ID with your execution ID
EXEC_ID=236377033309945856

curl -s http://localhost:8083/api/queue | python3 -c "
import sys, json
data = json.load(sys.stdin)
job = next((j for j in data.get('items', []) 
  if j.get('execution_id') == $EXEC_ID), None)
if job:
  print(f\"Status: {job['status']}\")
  print(f\"Attempts: {job['attempts']}/{job['max_attempts']}\")
  print(f\"Available at: {job['available_at']}\")
"
```

### 5. Verify Retry Events

#### Check Worker Logs
```bash
# See retry policy evaluation and events
strings logs/worker.log | grep -E "Retry policy evaluation|Emitted action_retry"

# Or for real-time monitoring
tail -f logs/worker.log | grep -i retry
```

#### Expected Output
```
Retry policy evaluation for job XXX: retry=True, delay=1s, attempt=2/3
Emitted action_retry event for job XXX, attempt 1/3
Retry policy evaluation for job XXX: retry=True, delay=2s, attempt=3/3
Emitted action_retry event for job XXX, attempt 2/3
Max retry attempts (3) reached for job XXX (current attempts: 3)
```

## Expected Test Results

### With max_attempts=3 (test_retry_always_fail_events.yaml)

**Attempt Sequence:**
1. **Attempt 1**: Execute → Fail → status=retry, attempts=1
2. **Attempt 2**: Execute → Fail → status=retry, attempts=2
3. **Attempt 3**: Execute → Fail → status=dead, attempts=3

**Final State:**
- Status: `dead`
- Attempts: `3/3` ✅
- Queue transitions: `queued → leased → retry → leased → retry → leased → dead`

**Events Emitted:**
1. `action_started` (attempt 1)
2. `action_error` (attempt 1 failure)
3. `action_retry` (retry scheduled, delay=1s)
4. `action_started` (attempt 2)
5. `action_error` (attempt 2 failure)
6. `action_retry` (retry scheduled, delay=1.5s)
7. `action_started` (attempt 3)
8. `action_error` (attempt 3 failure)
9. Job marked as `dead` (no more retries)

## Complete Retry Test Suite

### Run All Official Retry Tests

```bash
# This runs comprehensive retry tests
task test:local:retry-all
```

This will:
1. Reset the NoETL stack
2. Register all retry test playbooks:
   - `tests/retry/http_status_code`
   - `tests/retry/http_stop_condition`
   - `tests/retry/python_exception`
   - `tests/retry/duckdb_query`
   - `tests/retry/simple_config`
3. Execute each test sequentially
4. Display results

### Individual Test Execution

After running `task test:local:retry-all`, you can manually test:

```bash
# Python exception retry (recommended)
curl -X POST http://localhost:8083/api/executions/run \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/retry/python_exception"}'

# Simple config test
curl -X POST http://localhost:8083/api/executions/run \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/retry/simple_config"}'
```

## Verification Commands

### Check Queue Status
```bash
# View all retry jobs
curl -s http://localhost:8083/api/queue | python3 -c "
import sys, json
jobs = json.load(sys.stdin)['items']
retry_jobs = [j for j in jobs if j['status'] in ('retry', 'dead') and j['attempts'] > 0]
for j in retry_jobs:
    print(f\"Job {j['queue_id']}: {j['status']} - {j['attempts']}/{j['max_attempts']}\")
"
```

### Check Server/Worker Status
```bash
task noetl:local:status
```

### View Logs
```bash
# Server logs
tail -f logs/server.log | grep -i retry

# Worker logs
tail -f logs/worker.log | grep -i retry
```

## Troubleshooting

### Issue: Job marked dead with attempts=2/3

**Cause**: Old code still running (off-by-one error not fixed)

**Solution**: Restart with latest code
```bash
task noetl:local:stop
task noetl:local:start
```

### Issue: No retry events in logs

**Cause**: Worker not emitting action_retry events

**Solution**: Verify worker is running latest code
```bash
pkill -9 -f "noetl.main worker"
task noetl:local:worker-start
```

### Issue: Jobs not retrying at all

**Cause**: 
- Retry config not in playbook
- Worker not picking up retry jobs

**Solution**: 
1. Verify playbook has `retry` section
2. Check queue status includes "retry"
3. Restart server and worker

## Test Playbook Template

```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: my_retry_test
  path: tests/retry/my_test
  
workflow:
  - step: start
    next: [failing_task]
    
  - step: failing_task
    tool: python
    code: |
      def main(input_data):
          raise Exception("Intentional failure for testing")
    retry:
      max_attempts: 5
      initial_delay: 2.0
      backoff_multiplier: 1.5
      max_delay: 10.0
      jitter: false
      retry_when: "{{ error != None }}"
    next: [end]
    
  - step: end
```

## Key Features to Verify

✅ **Queue Status**: Check for "retry" status (not just "queued")
✅ **Attempt Count**: Verify attempts == max_attempts when dead
✅ **Action Retry Events**: Check worker logs for event emission
✅ **Exponential Backoff**: Verify increasing delays between retries
✅ **Retry Conditions**: Test retry_when/stop_when expressions

## Documentation References

- Complete implementation: `docs/RETRY_COMPLETE_IMPLEMENTATION.md`
- System overview: `docs/architecture_overview.md`
- Playbook DSL: `docs/dsl_spec.md`
- Testing guide: `docs/RETRY_TESTING_GUIDE.md`

## Summary

After resetting with `task noetl:local:start`:

1. ✅ Server and worker run with latest code
2. ✅ Register test playbook
3. ✅ Execute and monitor retry attempts
4. ✅ Verify attempts=3/3 before dead status
5. ✅ Check action_retry events in logs
6. ✅ Confirm retry status in queue

**Expected Result**: Jobs use ALL attempts (3/3, 5/5, etc.) before marking dead, with retry status and action_retry events providing full observability.
