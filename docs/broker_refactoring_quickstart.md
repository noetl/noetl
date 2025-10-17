# Event Processing Refactoring - Quick Start Guide

## What Changed?

The broker logic has been simplified. Instead of complex server-side loop handling and state tracking, the broker now just:

1. **Analyzes events** to determine execution state
2. **Evaluates transitions** defined in playbook `next` attributes  
3. **Enqueues next steps** or emits completion events

## Code Size Comparison

| Module | Old | New | Change |
|--------|-----|-----|--------|
| broker.py | 691 lines | 750 lines | +59 (clearer structure) |
| loop_completion.py | 1029 lines | - | Removed |
| iterator_completion.py | - | 262 lines | New (focused) |
| **Total Processing** | ~3600 lines | ~3000 lines | **-600 lines** |

## How to Use

### Option 1: Test in Parallel (Recommended)

```bash
# Keep old broker, add new one alongside
# Already done - broker_refactored.py exists

# To use new broker, update the import in dispatcher:
# From: from .processing.broker import evaluate_broker_for_execution
# To:   from .processing.broker_refactored import evaluate_broker_for_execution
```

### Option 2: Direct Replacement

```bash
# Backup old broker
mv noetl/server/api/event/processing/broker.py \
   noetl/server/api/event/processing/broker_old.py

# Use new broker
mv noetl/server/api/event/processing/broker_refactored.py \
   noetl/server/api/event/processing/broker.py

# Restart server
task noetl:local:reset
```

## Testing

### 1. Test Multi-Step Workflow

```bash
# Should execute all 3 steps
task playbook:local:execute \
  PLAYBOOK=tests/fixtures/playbooks/save_storage_test/create_tables \
  PORT=8083

# Check events - should see step_started for ALL steps
PGPASSWORD=demo psql -h localhost -p 54321 -U demo -d demo_noetl -c "
SELECT event_type, node_name, status 
FROM noetl.event 
WHERE execution_id = (
  SELECT execution_id FROM noetl.event 
  ORDER BY created_at DESC LIMIT 1
)
ORDER BY created_at;
"
```

Expected output:
```
execution_start   | (null)               | RUNNING
step_started      | create_flat_table    | RUNNING
action_started    | create_flat_table    | RUNNING
action_completed  | create_flat_table    | COMPLETED
step_completed    | create_flat_table    | COMPLETED
step_started      | create_nested_table  | RUNNING    ← Should appear!
action_started    | create_nested_table  | RUNNING
action_completed  | create_nested_table  | COMPLETED
step_completed    | create_nested_table  | COMPLETED
step_started      | create_summary_table | RUNNING    ← Should appear!
action_started    | create_summary_table | RUNNING
action_completed  | create_summary_table | COMPLETED
step_completed    | create_summary_table | COMPLETED
execution_complete| (null)               | COMPLETED
```

### 2. Test Iterator with Save

```bash
# Should process 3 items and save to database
task playbook:local:execute \
  PLAYBOOK=tests/fixtures/playbooks/iterator_save_test \
  PORT=8083

# Verify rows saved
PGPASSWORD=demo psql -h localhost -p 54321 -U demo -d demo_noetl -c "
SELECT * FROM public.iterator_save_test ORDER BY created_at DESC LIMIT 5;
"
```

### 3. Test Conditional Transitions

```bash
# Test playbook with when conditions
task playbook:local:execute \
  PLAYBOOK=tests/fixtures/playbooks/control_flow_workbook \
  PORT=8083
```

## Key Differences

### Event Flow

**Old Broker:**
- Complex loop expansion on server
- Multiple completion handlers
- Nested state tracking
- Proactive finalization

**New Broker:**
- Simple step-by-step progression
- Workers handle all iteration logic
- Server just routes based on events
- Clean event sequence

### Transition Handling

**Old:**
```python
# Deep in broker code, hard to follow
if step is loop:
    expand loop on server
    enqueue each iteration
    track completion state
    aggregate results
else:
    enqueue step
```

**New:**
```python
# Clear and simple
for transition in step.next:
    if evaluate_condition(transition.when):
        enqueue(transition.step)
```

### Iterator Steps

**Old:**
- Server detects iterator type
- Expands collection on server
- Enqueues multiple jobs
- Aggregates results
- ~500 lines of complex code

**New:**
- Server enqueues iterator step once
- Worker handles all iteration logic
- Worker emits iteration events
- Server only tracks child playbooks (if any)
- ~150 lines of clear code

## Rollback

If anything breaks:

```bash
# Put old broker back
mv noetl/server/api/event/processing/broker_old.py \
   noetl/server/api/event/processing/broker.py

# Restart
task noetl:local:reset
```

## What's Fixed

This refactoring specifically fixes the issue where only the first step in a multi-step workflow was executing. The problem was:

1. **Old broker**: After step_completed, called multiple complex handlers that might or might not enqueue the next step
2. **New broker**: After step_completed, directly evaluates transitions and enqueues next steps

The new code explicitly:
- Emits `step_completed` for finished steps
- Loads playbook and finds next transitions  
- Evaluates `when` conditions
- Emits `step_started` for next steps
- Enqueues tasks for next steps

## Next Steps

1. **Review** the refactored code in:
   - `noetl/server/api/event/processing/broker_refactored.py`
   - `noetl/server/api/event/processing/iterator_completion.py`

2. **Test** with your common playbooks

3. **Deploy** by updating the import in the dispatcher

4. **Monitor** event logs to verify correct flow

5. **Clean up** old files once stable

## Questions?

See `docs/broker_refactoring_summary.md` for complete details.
