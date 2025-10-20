# Event Processing Refactoring Summary

## Overview

Refactored the `noetl/server/api/event/processing` package to simplify broker logic and remove legacy code. The broker now has a clear, simple responsibility: analyze events and decide what to enqueue or emit next.

## Key Changes

### 1. Simplified Broker Logic

**New File: `broker_refactored.py`**

The broker now follows a simple flow:

```
Event → Analyze → Decide → Enqueue or Emit
```

**Core Functions:**

- `evaluate_broker_for_execution()` - Main entry point
  - Check for failures (stop if failed)
  - Initial dispatch (enqueue first step)
  - Process completed steps (evaluate transitions, enqueue next)

- `_dispatch_first_step()` - Handle new executions
  - Load playbook and context
  - Find first actionable step from 'start'
  - Emit step_started
  - Enqueue task

- `_process_completed_steps()` - Handle step completions
  - Find completed but not finalized steps
  - Emit step_completed
  - Evaluate transitions with 'when' conditions
  - Enqueue next actionable steps

**Benefits:**
- Clear separation of concerns
- No complex state tracking on server
- Each step executes independently
- Simple condition evaluation for transitions

### 2. Renamed Loop → Iterator

**New File: `iterator_completion.py`** (replaces `loop_completion.py`)

This module now has a focused purpose: handle iterator steps that spawn child playbook executions. Regular iterator steps complete entirely on workers and don't need server-side aggregation.

**Core Functions:**

- `check_iterator_child_completions()` - Check if iterator with child executions completed
  - Only for `type: playbook` iterators
  - Aggregates results from child executions
  - Emits iterator_completed when all children done

- `finalize_direct_iterators()` - Fallback for worker-completed iterators
  - Aggregates per-iteration results
  - Emits iterator_completed event

**Event Changes:**
- `loop_iteration` → `iteration_started`
- `end_loop` → `iterator_completed`
- No more TRACKING state on server

### 3. Removed Legacy Code

**Deleted Concepts:**
- Server-side loop expansion
- Complex loop state tracking
- Multiple completion handlers
- Proactive finalization logic

**What Was Removed:**
- ~500 lines of complex loop handling code
- Nested iteration tracking
- Server-side loop enumeration
- Legacy transition resolution

### 4. Clear Event Flow

**Old Flow (Complex):**
```
Event → Broker → Loop Handler → Child Handler → Retry Handler → Broker Again → Enqueue
```

**New Flow (Simple):**
```
Event → Broker → Evaluate Transitions → Enqueue Next Steps
```

**Event Sequence for Multi-Step Workflow:**
```
1. execution_start
2. step_started (step1)
3. action_started (step1)
4. action_completed (step1)
5. step_completed (step1)    ← Broker evaluates transitions
6. step_started (step2)       ← Broker enqueues next
7. action_started (step2)
8. action_completed (step2)
9. step_completed (step2)
10. step_started (step3)
... and so on
```

### 5. Transition Evaluation

**Condition Evaluation:**
```yaml
workflow:
  - step: check_weather
    type: http
    next:
      - when: "{{ check_weather.data.temperature > 80 }}"
        step: send_alert
        data:
          temp: "{{ check_weather.data.temperature }}"
      - when: "{{ check_weather.data.temperature <= 80 }}"
        step: log_normal
```

**Implementation:**
- Load all step results into evaluation context
- Evaluate each `when` condition using Jinja2
- Enqueue only steps where condition is true
- Support multiple parallel transitions

### 6. File Structure

**Before:**
```
processing/
  ├── broker.py (691 lines, complex)
  ├── loop_completion.py (1030 lines, legacy)
  ├── child_executions.py (342 lines)
  ├── workflow.py
  └── retry.py
```

**After:**
```
processing/
  ├── broker_refactored.py (750 lines, clean)
  ├── iterator_completion.py (260 lines, focused)
  ├── child_executions.py (keep for compatibility)
  ├── workflow.py (unchanged)
  └── retry.py (unchanged)
```

## Implementation Plan

### Phase 1: Parallel Testing (Recommended)
1. Keep old broker.py
2. Add broker_refactored.py alongside
3. Test with feature flag: `NOETL_USE_REFACTORED_BROKER=true`
4. Run integration tests in both modes
5. Compare event logs and execution results

### Phase 2: Migration
1. Verify all test playbooks work with new broker
2. Update imports in dispatcher to use broker_refactored
3. Rename broker.py → broker_legacy.py
4. Rename broker_refactored.py → broker.py
5. Update iterator_completion imports

### Phase 3: Cleanup
1. Delete broker_legacy.py
2. Delete loop_completion.py
3. Update documentation
4. Remove old event types from schema

## Benefits

### For Development
- **Easier to understand**: Clear flow, single responsibility
- **Easier to debug**: Less state, more explicit events
- **Easier to test**: Isolated functions, predictable behavior

### For Users
- **More predictable**: Each step is independent
- **Better visibility**: Clear event sequence
- **Faster execution**: Less server overhead

### For Performance
- **Reduced database queries**: No complex state reconstruction
- **Simpler transactions**: One query per enqueue
- **Better parallelism**: Steps can run concurrently

## Breaking Changes

### Event Types (if we clean up)
- Remove `loop_iteration` (use `iteration_started`)
- Remove `end_loop` (use `iterator_completed`)
- Keep both during transition for compatibility

### Playbook Compatibility
- All existing playbooks continue to work
- `loop:` already normalized to `iterator:` by DSL
- No changes needed to playbook syntax

## Testing Checklist

- [ ] Simple linear workflow (A → B → C)
- [ ] Conditional transitions with `when`
- [ ] Iterator with nested tasks
- [ ] Iterator with child playbooks
- [ ] Parallel transitions (multiple next steps)
- [ ] Save blocks on steps
- [ ] Retry with backoff
- [ ] Error handling and failures
- [ ] End step with result mapping
- [ ] Workbook steps

## Migration Commands

```bash
# Test with new broker
export NOETL_USE_REFACTORED_BROKER=true
task test-control-flow-workbook-full

# Compare event logs
PGPASSWORD=demo psql -h localhost -p 54321 -U demo -d demo_noetl -c "
SELECT execution_id, event_type, node_name, status 
FROM noetl.event 
WHERE execution_id IN (
  SELECT execution_id FROM noetl.event 
  WHERE created_at > NOW() - INTERVAL '1 hour'
)
ORDER BY execution_id, created_at;
"

# Verify step transitions
task playbook:local:execute PLAYBOOK=tests/fixtures/playbooks/save_storage_test/create_tables PORT=8083
```

## Rollback Plan

If issues are found:

1. Set `NOETL_USE_REFACTORED_BROKER=false`
2. Restart server: `task noetl:local:reset`
3. Old broker resumes handling events
4. No data loss - events persist regardless

## Documentation Updates Needed

1. Update architecture overview
2. Update execution model docs
3. Update event schema docs
4. Add transition evaluation guide
5. Update iterator documentation

## Future Enhancements

With simpler broker, we can now easily add:

- Parallel step execution (fan-out)
- Dynamic step generation
- Conditional step skipping
- Step-level timeouts
- Better error recovery strategies
- Workflow visualization
