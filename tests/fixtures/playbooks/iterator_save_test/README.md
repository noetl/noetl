# Iterator Save Test

This folder contains a test for **per-iteration sink execution** using NoETL's v2 event-driven architecture.

## 🎯 Test Type

**✅ Loop + Sink Pattern**
- Sequential loop over collection
- Per-iteration sink execution
- Event-driven data persistence

## Overview

The `iterator_save_test.yaml` playbook demonstrates **per-iteration sink execution** where:
- Loop processes items sequentially from a collection
- Each iteration emits `step.exit` event
- Sink evaluates and executes for each iteration
- Results are written to database per item

**Test Scenario:**
- **Collection**: 3 items (item1/100, item2/200, item3/300)
- **Loop Mode**: Sequential
- **Events**: Each iteration triggers `step.exit` event
- **Sink Trigger**: Evaluates on `event.name == 'step.exit'`
- **Expected Rows**: 3 (one per iteration)

## Files

- `iterator_save_test.yaml` - Playbook definition with loop + sink pattern
- `README.md` - This file

## Key Concepts

### Event Lifecycle in Loops

NoETL v2 emits events at different stages:
- `step.enter` - Before tool execution starts
- `call.done` - After tool execution completes
- `step.exit` - **After each loop iteration** (critical for per-iteration sinks)
- `loop.done` - After all iterations complete
- `command.completed` - Final command completion

### Per-Iteration Sinks

```yaml
loop:
  in: "{{ workload.items }}"
  iterator: item
  mode: sequential

case:
  - when: "{{ event.name == 'step.exit' and response is defined }}"
    then:
      - sink:
          tool:
            kind: postgres
            auth: "{{ workload.pg_auth }}"
            statement: |
              INSERT INTO public.iterator_save_test (id, execution_id, item_name, item_value)
              VALUES (
                '{{ execution_id }}:{{ response.item_name }}',
                '{{ execution_id }}',
                '{{ response.item_name }}',
                {{ response.item_value }}
              )
  
  - when: "{{ event.name == 'loop.done' }}"
    then:
      - next:
          - step: end
```

**Key Points:**
- **Event condition**: `step.exit` is emitted per iteration, NOT `call.done`
- **Sink evaluation**: Each iteration evaluates sink condition separately
- **Data flow**: `response.item_name` and `response.item_value` come from Python tool output
- **Loop completion**: `loop.done` event signals all iterations finished
- **YAML structure**: `then` must be list format: `then: [- sink:..., - next:...]`

## Database Schema

```sql
CREATE TABLE IF NOT EXISTS public.iterator_save_test (
  id TEXT PRIMARY KEY,
  execution_id TEXT,
  item_name TEXT,
  item_value INTEGER,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

## Expected Results

After successful execution:

```sql
SELECT * FROM public.iterator_save_test WHERE execution_id = '<execution_id>';
```

**Expected Rows:**
```
id                      | execution_id  | item_name | item_value | created_at
------------------------|---------------|-----------|------------|---------------------------
<execution_id>:item1    | <execution_id>| item1     | 100        | 2026-01-04 14:15:32.123+00
<execution_id>:item2    | <execution_id>| item2     | 200        | 2026-01-04 14:15:32.456+00
<execution_id>:item3    | <execution_id>| item3     | 300        | 2026-01-04 14:15:32.789+00
```

## How to Run

### Using NoETL API

```bash
# Register playbook
curl -X POST http://localhost:8082/api/catalog/register \
  -H "Content-Type: application/json" \
  -d '{
    "path": "tests/fixtures/playbooks/iterator_save_test/iterator_save_test",
    "content": "<base64_encoded_yaml>"
  }'

# Execute playbook
curl -X POST http://localhost:8082/api/execute \
  -H "Content-Type: application/json" \
  -d '{
    "path": "tests/fixtures/playbooks/iterator_save_test/iterator_save_test"
  }'
```

### Using Task

```bash
# Full test: deploy + register + execute
task test:iterator-save:full
```

### Verify Results

```bash
# Query database
kubectl exec -n postgres deployment/postgres -- \
  psql -U demo -d demo_noetl -c \
  "SELECT * FROM public.iterator_save_test ORDER BY created_at;"
```

## Common Issues

### Issue: No rows inserted (table empty)

**Symptom**: Playbook completes successfully but table has 0 rows

**Root Cause**: Wrong event name in case condition
- ❌ `when: "{{ event.name == 'call.done' }}"` - Wrong! Only emitted once after all iterations
- ✅ `when: "{{ event.name == 'step.exit' }}"` - Correct! Emitted per iteration

**Fix**: Change case condition to use `step.exit` event

### Issue: YAML structure error

**Symptom**: Sink not executing, no CASE-CHECK logs

**Root Cause**: Incorrect YAML structure for `then` block
- ❌ `then: {sink:..., next:...}` - Wrong! Dictionary format
- ✅ `then: [- sink:..., - next:...]` - Correct! List format

**Fix**: Convert `then` block to list format

### Issue: Template error "undefined variable"

**Symptom**: Template rendering failed logs in worker

**Root Cause**: Accessing wrong context variable
- ❌ `{{ data.field }}` - `data` not in context
- ✅ `{{ response.field }}` or `{{ result.field }}` - Correct context variables

**Fix**: Use proper template context variables

## Related Tests

- [json_serialization_save](../json_serialization_save/) - JSONB column persistence
- [pagination/loop_with_pagination](../pagination/loop_with_pagination/) - Iterator + pagination combo
- [control_flow_workbook](../control_flow_workbook/) - Complex conditional routing

## Technical Details

**NoETL Version**: v2 (event-driven architecture)
**Worker**: v2_worker_nats.py handles event evaluation and sink execution
**Server**: Routes workflow based on events, does not handle sinks
**Event Source**: Worker emits events after tool execution
**Sink Executor**: Worker evaluates case conditions and executes sinks locally

## Validation

This playbook was fixed as part of debugging session on 2026-01-04:

**Original Issue**: Table empty after successful execution
**Root Cause**: Used `call.done` event instead of `step.exit`
**Fix**: Changed condition to `step.exit` 
**Verification**: Execution 532653790558683983 inserted 3 rows correctly

**Test Status**: ✅ PASSED
