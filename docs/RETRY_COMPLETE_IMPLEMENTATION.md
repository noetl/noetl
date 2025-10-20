# NoETL Retry System - Complete Implementation Summary

## ✅ All Features Working

### 1. Retry Configuration Flow
- ✅ Retry config copied from playbook step to broker task
- ✅ `max_attempts` extracted from retry config (bool/int/dict formats)
- ✅ Retry config included in queue job action
- ✅ Dynamic max_attempts passed to queue INSERT

### 2. Queue Status Management
- ✅ New "retry" status for jobs waiting to retry
- ✅ Status transitions: queued → leased → retry → leased → retry → ... → dead
- ✅ Worker lease picks up both "queued" and "retry" status jobs
- ✅ Available_at timestamp controls when retry jobs become available

### 3. Retry Policy Evaluation
- ✅ Worker evaluates retry policy on job failure
- ✅ Checks current attempts vs max_attempts correctly
- ✅ RetryPolicy evaluates retry_when/stop_when Jinja2 conditions
- ✅ Exponential backoff delays calculated correctly
- ✅ Jobs retry until all attempts exhausted (attempts == max_attempts)

### 4. Event Tracking
- ✅ `action_retry` events emitted when jobs retry
- ✅ Events include attempt number, max_attempts, retry_delay_seconds
- ✅ Events provide full observability of retry behavior

### 5. Queue Table Fields
- ✅ `status`: "queued", "leased", "retry", "done", "dead"
- ✅ `attempts`: Current attempt count (incremented on lease)
- ✅ `max_attempts`: Maximum attempts from retry config
- ✅ `available_at`: Timestamp when retry job becomes available

## Test Results

### Test: max_attempts=3
- ✅ Attempt 1: Execute → Fail → Retry (status=retry, attempts=1)
- ✅ Attempt 2: Execute → Fail → Retry (status=retry, attempts=2)
- ✅ Attempt 3: Execute → Fail → Dead (status=dead, attempts=3)
- ✅ Final state: attempts=3/3, status=dead ✅

### Test: max_attempts=5
- ✅ All 5 attempts executed before marking dead
- ✅ Exponential backoff delays: 2s → 3s → 4.5s → 6.75s
- ✅ Final state: attempts=5/5, status=dead ✅

## Files Modified

### 1. Broker (`noetl/server/api/event/processing/broker.py`)
- Added `'retry'` to fields copied from step to task (line ~268)
- Extract max_attempts from retry config (lines ~422-430)
- Pass dynamic max_attempts to queue INSERT (line ~456)

### 2. Queue Service (`noetl/server/api/queue/service.py`)
- Updated fail_job to set status='retry' when retrying (line ~724)
- Updated lease_job to include 'retry' status (line ~159)
- Updated reserve_job to include 'retry' status (line ~871)

### 3. Worker (`noetl/worker/worker.py`)
- Modified `_fail_job()` to accept job parameter and emit action_retry events (lines 369-428)
- Fixed retry evaluation to check current_attempts vs max_attempts (lines 487-498)
- Updated `_execute_job()` to pass job to `_fail_job()` (line ~1002)

### 4. Retry Policy (`noetl/plugin/tool/retry.py`)
- Fixed off-by-one error: check `attempt > max_attempts` not `>=` (line ~75)

## Key Fixes Applied

### Fix #1: Off-by-One Error in Attempt Counting
**Problem**: Jobs were marked dead with attempts=2/3 or 4/5
**Root Cause**: Worker checked `attempt_number >= max_attempts` where attempt_number = attempts + 1
**Solution**: Changed to check `current_attempts >= max_attempts` in worker, and `attempt > max_attempts` in RetryPolicy

### Fix #2: Missing "retry" Queue Status
**Problem**: No way to distinguish retrying jobs from new jobs
**Solution**: Added "retry" status, updated all lease queries to include it

### Fix #3: No Retry Event Tracking
**Problem**: No visibility into retry attempts in event log
**Solution**: Emit `action_retry` events with attempt counts and delays

### Fix #4: Retry Config Not Passed to Worker
**Problem**: Worker couldn't evaluate retry policy
**Solution**: Added 'retry' to broker field copy list, included in action JSON

## How to Test

```bash
# Create always-fail test playbook
cat > test_retry.yaml << 'EOF'
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: test_retry_verification
  path: tests/retry/verify
workflow:
  - step: start
    next: [fail_task]
  - step: fail_task
    type: python
    code: |
      def main(input_data):
          raise Exception("Test retry")
    retry:
      max_attempts: 3
      initial_delay: 1.0
      retry_when: "{{ error != None }}"
    next: [end]
  - step: end
EOF

# Register and execute
noetl register test_retry.yaml
curl -X POST http://localhost:8083/api/executions/run \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/retry/verify"}'

# Monitor queue status
watch -n 1 'curl -s http://localhost:8083/api/queue | \
  python3 -m json.tool | grep -E "status|attempts"'

# Check worker logs for retry events
tail -f logs/worker.log | grep -i "retry\|Emitted"
```

## Expected Behavior

1. **First execution**: status=leased, attempts=1
2. **First failure**: status=retry, attempts=1, available_at=now+1s
3. **Second execution**: status=leased, attempts=2
4. **Second failure**: status=retry, attempts=2, available_at=now+1.5s
5. **Third execution**: status=leased, attempts=3
6. **Third failure**: status=dead, attempts=3 (no more retries)

## Observability

### Queue Table
```sql
SELECT queue_id, status, attempts, max_attempts, available_at
FROM noetl.queue
WHERE execution_id = <ID>;
```

### Event Log
```sql
SELECT event_type, node_name, result
FROM noetl.event
WHERE execution_id = <ID>
AND event_type IN ('action_started', 'action_error', 'action_retry', 'action_completed');
```

### Worker Logs
```bash
grep -i "retry policy evaluation\|emitted action_retry" logs/worker.log
```

## Summary

✅ **Retry system fully functional**
- All attempts executed before marking dead
- "retry" status provides clear queue state
- action_retry events provide full observability
- Exponential backoff working correctly
- Jinja2 retry conditions evaluated properly

The retry mechanism is now production-ready and properly integrated with the event-driven architecture!
