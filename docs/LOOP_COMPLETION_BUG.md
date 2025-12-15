# Loop/Iterator Completion Bug - Critical Issue

## Summary
When a playbook step has a `loop:` attribute, the server expands it into multiple iteration jobs (`step_name_iter_0`, `step_name_iter_1`, etc.). After all iterations complete, the workflow hangs because the parent step never gets an `action_completed` event, preventing `_process_transitions` from moving to the next step.

## Reproduction
**Playbook**: `tests/pagination/loop_with_pagination/loop_with_pagination`
**Test Execution**: 512647364641817386

### Playbook Structure
```yaml
- step: fetch_all_endpoints
  tool: http
  loop:
    collection: "{{ workload.endpoints }}"
    element: endpoint
    mode: sequential
  url: "{{ workload.api_url }}{{ endpoint.path }}"
  retry:
    on_success:
      while: "{{ response.paging.hasMore == true }}"
      ...
  next:
    - step: validate_results
```

### Observed Behavior
```
Event Log:
1. playbook_started (STARTED)
2. workflow_initialized (COMPLETED)
3. iterator_started (RUNNING) - node_id: fetch_all_endpoints
4. action_started (RUNNING) - node_name: fetch_all_endpoints_iter_0
5. action_completed (COMPLETED) - node_name: fetch_all_endpoints_iter_0
6. step_result (COMPLETED) - node_name: fetch_all_endpoints_iter_0
7. action_started (RUNNING) - node_name: fetch_all_endpoints_iter_1
8. action_completed (COMPLETED) - node_name: fetch_all_endpoints_iter_1
9. step_result (COMPLETED) - node_name: fetch_all_endpoints_iter_1
10. action_started (RUNNING) - node_name: fetch_all_endpoints_iter_2
11. action_completed (COMPLETED) - node_name: fetch_all_endpoints_iter_2
12. step_result (COMPLETED) - node_name: fetch_all_endpoints_iter_2
[STUCK HERE - No more events]
```

### Expected Behavior
```
... (same as above)
13. iterator_completed (COMPLETED) - node_name: fetch_all_endpoints
14. action_completed (COMPLETED) - node_name: fetch_all_endpoints  # MISSING
15. step_completed (COMPLETED) - node_name: fetch_all_endpoints
16. action_started (RUNNING) - node_name: validate_results
...
```

## Root Cause Analysis

### 1. Server-Side Iterator Expansion
When `_process_transitions` encounters a step with `loop:` attribute, it emits an `iterator_started` event. The `_process_iterator_started` function (line 1661 in orchestrator.py) then creates separate queue jobs for each iteration:

```python
# Line 1771-1772
node_id=f"{event.get('node_id')}_iter_{batch['index']}",
node_name=f"{event.get('node_name')}_iter_{batch['index']}",
```

**Result**: 3 queue jobs created:
- `fetch_all_endpoints_iter_0`
- `fetch_all_endpoints_iter_1`
- `fetch_all_endpoints_iter_2`

### 2. Workers Execute Iterations
Workers pick up each iteration job and execute successfully. Each emits:
- `action_started` (with `_iter_N` suffix)
- `action_completed` (with `_iter_N` suffix)
- `step_result` (with `_iter_N` suffix)

**Result**: All 3 iteration jobs complete and are marked `done` in queue.

### 3. Transition Processing Failure
The `_process_transitions` function (line 928) looks for completed steps:

```python
# Line 944
completed_steps = await OrchestratorQueries.get_completed_steps_without_step_completed(execution_id)
```

This query returns steps that have `action_completed` events but no `step_completed` events:

```sql
SELECT DISTINCT node_name
FROM noetl.event
WHERE execution_id = %(execution_id)s
  AND event_type = 'action_completed'
  AND node_name NOT IN (
      SELECT node_name FROM noetl.event
      WHERE execution_id = %(execution_id)s AND event_type = 'step_completed'
  )
```

**Result**: Returns `['fetch_all_endpoints_iter_0', 'fetch_all_endpoints_iter_1', 'fetch_all_endpoints_iter_2']`

**Problem**: The parent step `fetch_all_endpoints` is NOT in this list because it never had an `action_completed` event!

### 4. Loop Detection Logic
The code at lines 1025-1042 has logic to check for pending iterations:

```python
if step_def.get("loop"):
    logger.info(f"Step '{step_name}' has loop attribute, checking for pending iterations")
    # Check if there are pending iteration jobs
    await cur.execute(...)
    pending_count = pending_row['pending_count'] if pending_row else 0
    
    if pending_count > 0:
        logger.info(f"Step '{step_name}' has {pending_count} pending iteration jobs, skipping...")
        continue  # Skip this step for now
    else:
        logger.info(f"All iterations complete for step '{step_name}', proceeding with transitions")
```

**Problem**: This code only runs IF `step_name` is already in `completed_steps`. But `fetch_all_endpoints` is NOT in that list, so this code never executes!

### 5. Missing Parent Completion
The iteration jobs complete successfully, but:
1. No `action_completed` event for parent step `fetch_all_endpoints`
2. No `step_completed` event for parent step
3. `_process_transitions` never processes the parent step
4. Workflow never moves to next step (`validate_results`)

## Database Evidence

### Queue Jobs (All Done)
```sql
SELECT node_name, status FROM noetl.queue WHERE execution_id = 512647364641817386;
```
```
fetch_all_endpoints_iter_0  done
fetch_all_endpoints_iter_1  done
fetch_all_endpoints_iter_2  done
```

### Events (Missing Parent Completion)
```sql
SELECT event_type, node_name FROM noetl.event WHERE execution_id = 512647364641817386 ORDER BY event_id;
```
```
iterator_started       iterator
action_started         fetch_all_endpoints_iter_0
action_completed       fetch_all_endpoints_iter_0
step_result            fetch_all_endpoints_iter_0
action_started         fetch_all_endpoints_iter_1
action_completed       fetch_all_endpoints_iter_1
step_result            fetch_all_endpoints_iter_1
action_started         fetch_all_endpoints_iter_2
action_completed       fetch_all_endpoints_iter_2
step_result            fetch_all_endpoints_iter_2
# Missing: action_completed/step_completed for 'fetch_all_endpoints'
```

## Solution Options

### Option 1: Emit Parent Action Completed (Recommended)
Modify `_process_iterator_started` to emit an `action_completed` event for the parent step after all iterations complete.

**Location**: `noetl/server/api/run/orchestrator.py`, around line 1790

**Approach**:
1. After detecting all iteration jobs are done, emit `action_completed` for parent step
2. This will add parent step to `completed_steps` in next `_process_transitions` call
3. Existing loop detection logic (lines 1025-1042) will then proceed with step_completed

### Option 2: Modify Query to Include Parents
Modify `get_completed_steps_without_step_completed` to also return parent steps when all their iteration children are complete.

**Location**: `noetl/server/api/run/queries.py`, line 147

**Approach**:
1. Add additional query logic to detect complete iterations
2. Return parent step name when all `{parent}_iter_*` jobs done
3. May be complex to implement correctly

### Option 3: Add Iterator Completion Handler
Create a dedicated handler that watches for all iteration completions and emits parent events.

**Location**: New function in `noetl/server/api/run/orchestrator.py`

**Approach**:
1. Call from `evaluate_execution` after `_process_transitions`
2. Check for steps with completed iterations but no parent completion
3. Emit parent `action_completed` and `step_completed` events

## Temporary Workaround

Remove the `loop:` attribute and manually iterate:

```yaml
# Instead of loop at step level
- step: fetch_endpoint_1
  tool: http
  url: "{{ workload.api_url }}/api/v1/assessments"
  retry:
    on_success: ...

- step: fetch_endpoint_2
  tool: http
  url: "{{ workload.api_url }}/api/v1/assessments"
  retry:
    on_success: ...

- step: fetch_endpoint_3
  tool: http
  url: "{{ workload.api_url }}/api/v1/assessments"
  retry:
    on_success: ...
```

This avoids the iterator expansion issue but loses dynamic iteration capability.

## Impact

**Severity**: CRITICAL - Production Blocker

**Affects**:
- All playbooks using `loop:` attribute at step level
- Master regression test (includes loop_with_pagination test)
- Production deployment validation

**Does NOT Affect**:
- Steps without `loop:` attribute
- Direct HTTP pagination (retry.on_success without loop)
- Old iterator patterns (tool: iterator)

## Next Steps

1. **Immediate**: Apply Option 1 fix to emit parent action_completed
2. **Testing**: Re-run loop_with_pagination test to verify
3. **Validation**: Run master regression test to ensure no regressions
4. **Documentation**: Update loop/iterator documentation with this limitation

## References

- **Playbook**: `tests/fixtures/playbooks/pagination/loop_with_pagination/test_loop_with_pagination.yaml`
- **Orchestrator**: `noetl/server/api/run/orchestrator.py`
- **Queries**: `noetl/server/api/run/queries.py`
- **Test Executions**: 512641566788289305, 512647364641817386
- **Related Docs**: `docs/distributed_loop_retry_architecture.md`, `docs/broker_refactoring_summary.md`
