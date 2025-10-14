# NoETL Queue Retry Status Flow - Verification

## Queue Status Lifecycle

### Complete Status Transitions for max_attempts=3

```
Initial: queued (0/3)
   ↓ [worker leases job]
Attempt 1: leased (1/3)
   ↓ [execution fails]
Wait: retry (1/3)          ← Job waiting to retry
   ↓ [available_at reached, worker leases]
Attempt 2: leased (2/3)
   ↓ [execution fails]
Wait: retry (2/3)          ← Job waiting to retry
   ↓ [available_at reached, worker leases]
Attempt 3: leased (3/3)
   ↓ [execution fails, attempts == max_attempts]
Final: dead (3/3)          ← All attempts exhausted
```

## Status Definitions

| Status  | Meaning | When Applied |
|---------|---------|--------------|
| `queued` | New job waiting for first execution | Job created by broker |
| `leased` | Worker actively executing the job | Worker calls lease_job |
| `retry` | Job waiting to retry after failure | Worker calls fail_job with retry=True |
| `dead` | All attempts exhausted, no more retries | attempts >= max_attempts |
| `done` | Job completed successfully | Worker calls complete_job |

## Key Requirements Met

✅ **Retry Status During Attempts**
- Job marked as "retry" (not "dead") when waiting between attempts
- Clear distinction from completed/failed jobs

✅ **Leased Status on Acquisition**
- Job changes from "retry" to "leased" when worker picks it up
- Worker can track active vs waiting jobs

✅ **Dead Only After All Attempts**
- Job marked "dead" ONLY when attempts == max_attempts
- Never marked dead prematurely (e.g., 2/3 attempts)

## Verified Test Results

### Test Execution: 236378361868320768
**Configuration**: max_attempts=3

**Status Timeline:**
```
Check 2: queued  | 0/3  ← Initial
Check 3: retry   | 1/3  ← After 1st failure
Check 5: retry   | 2/3  ← After 2nd failure  
Check 8: leased  | 3/3  ← 3rd attempt executing
Check 9: dead    | 3/3  ← All attempts used ✅
```

**Result**: ✅ CORRECT - status=dead, attempts=3/3

## Queue Queries

### Jobs Waiting to Retry
```sql
SELECT * FROM noetl.queue 
WHERE status = 'retry' 
  AND available_at <= now();
```

### Active Executions
```sql
SELECT * FROM noetl.queue 
WHERE status = 'leased';
```

### Failed Jobs (All Attempts Exhausted)
```sql
SELECT * FROM noetl.queue 
WHERE status = 'dead' 
  AND attempts = max_attempts;
```

## Worker Lease Logic

The worker lease query picks up both new jobs and retry jobs:

```sql
WHERE status IN ('queued', 'retry') 
  AND (available_at IS NULL OR available_at <= now())
```

This ensures:
- New jobs (`queued`) are picked up immediately
- Retry jobs (`retry`) are picked up only after `available_at` timestamp

## Status Transitions in Code

### Server (fail_job in queue/service.py)
```python
if retry is False:
    status = 'dead'
elif attempts >= max_attempts:
    status = 'dead'
else:
    status = 'retry'  # Job will retry
    available_at = now() + retry_delay_seconds
```

### Worker (lease_job)
```python
# When worker leases a job:
UPDATE noetl.queue 
SET status = 'leased',
    attempts = attempts + 1
WHERE status IN ('queued', 'retry')
```

## Event Correlation

Each status transition corresponds to events:

| Queue Status | Related Events |
|--------------|----------------|
| `queued` | `step_started` (broker enqueues) |
| `leased` | `action_started` (worker begins execution) |
| `retry` | `action_error` + `action_retry` (worker schedules retry) |
| `dead` | `action_error` (no retry event) |
| `done` | `action_completed` |

## Troubleshooting

### Job stuck in "retry" status
**Check**: Is `available_at` in the future?
```bash
curl -s http://localhost:8083/api/queue | python3 -c "
import sys, json
from datetime import datetime
jobs = json.load(sys.stdin)['items']
retry_jobs = [j for j in jobs if j['status'] == 'retry']
for j in retry_jobs:
    print(f\"Job {j['queue_id']}: available_at={j['available_at']}\")
"
```

### Job marked "dead" too early
**Check**: Was it created with old code?
- Old code had off-by-one error (checked attempt_number >= max_attempts)
- New code correctly checks current_attempts >= max_attempts
- Solution: Re-execute with fresh server/worker

### No "retry" status, only "dead"
**Check**: Is retry configured?
```bash
curl -s http://localhost:8083/api/queue | python3 -c "
import sys, json
jobs = json.load(sys.stdin)['items']
job = jobs[-1]
action = json.loads(job['action'])
print(f\"Retry config: {action.get('retry', 'NOT CONFIGURED')}\")
"
```

## Summary

The queue status system provides full visibility into retry behavior:

1. **"queued"** - New job, never executed
2. **"leased"** - Worker actively executing (attempts incremented)
3. **"retry"** - Failed, waiting to retry (with available_at delay)
4. **"dead"** - All attempts exhausted, no more retries
5. **"done"** - Successfully completed

This ensures:
- Clear distinction between active, waiting, and failed jobs
- Worker can efficiently query for jobs to execute
- Full observability of retry state
- Jobs never marked dead until ALL attempts used

✅ **Status**: Production-ready and working correctly
