# JSON Serialization Save Test

This folder contains a test for **JSON/JSONB column persistence** using NoETL's v2 event-driven architecture.

## 🎯 Test Type

**✅ JSON Serialization + JSONB Storage**
- Python dict output serialization
- JSONB column persistence
- Template-based JSON formatting

## Overview

The `json_serialization_save.yaml` playbook demonstrates **JSON serialization to JSONB column** where:
- Python tool returns complex dict with nested objects and arrays
- Template engine serializes dict to JSON string using `tojson` filter
- Postgres stores JSON in JSONB column for efficient querying
- Validation step confirms data persisted correctly

**Test Scenario:**
- **Tool**: Python async function returning nested dict
- **Serialization**: Jinja2 `tojson` filter with SQL escaping
- **Storage**: PostgreSQL JSONB column
- **Validation**: Query to verify JSON structure

## Files

- `json_serialization_save.yaml` - Playbook definition with JSONB persistence
- `README.md` - This file

## Key Concepts

### JSON to JSONB Workflow

1. **Python Returns Dict**: Tool execution produces structured data
2. **Template Serializes**: `{{ result.data | tojson }}` converts to JSON string
3. **SQL Escapes Quotes**: `replace("'", "''")` handles single quotes in JSON
4. **JSONB Cast**: `::jsonb` ensures proper PostgreSQL type
5. **Validation**: Query confirms data structure preserved

### JSONB Sink Pattern

```yaml
- step: save_dict_to_jsonb
  tool:
    kind: python
    code: |
      async def main(input_data):
          return {
              "data": {
                  "string_field": "test_value",
                  "number_field": 42,
                  "nested_object": {
                      "key1": "value1",
                      "key2": "value2"
                  },
                  "array_field": [1, 2, 3, 4, 5]
              }
          }
  
  case:
    - when: "{{ event.name == 'step.exit' and response is defined }}"
      then:
        - sink:
            tool:
              kind: postgres
              auth: "{{ workload.pg_auth }}"
              statement: >
                INSERT INTO public.json_bug_test (id, payload)
                VALUES (1, '{{ result.data | tojson | replace("'", "''") }}'::jsonb)
        - next:
            - step: verify_save
```

**Key Points:**
- **Event condition**: `step.exit` is correct event for sink evaluation
- **Template access**: `result.data` accesses Python tool's return value
- **JSON filter**: `tojson` converts Python dict to JSON string
- **SQL escaping**: `replace("'", "''")` prevents SQL injection
- **JSONB cast**: `::jsonb` enables PostgreSQL JSON indexing and querying
- **YAML structure**: `then` must be list: `then: [- sink:..., - next:...]`
- **Sink format**: Only `tool:` block with `kind`, `auth`, `statement` - no extra fields

## Database Schema

```sql
DROP TABLE IF EXISTS public.json_bug_test;
CREATE TABLE public.json_bug_test (
  id INTEGER PRIMARY KEY,
  payload JSONB
);
```

**JSONB Benefits:**
- Binary storage format (faster than JSON text)
- Indexable fields for queries
- Supports operators: `->`, `->>`, `@>`, `?`, etc.
- Automatic validation on insert

## Expected Results

After successful execution:

```sql
SELECT * FROM public.json_bug_test WHERE id = 1;
```

**Expected Row:**
```
id | payload
----|-------------------------------------------------------------------------
 1  | {"array_field": [1, 2, 3, 4, 5], "number_field": 42, "string_field": "test_value", "nested_object": {"key1": "value1", "key2": "value2"}}
```

**JSONB Queries:**
```sql
-- Extract nested field
SELECT payload->'nested_object'->>'key1' FROM json_bug_test WHERE id = 1;
-- Result: "value1"

-- Check array contains value
SELECT payload FROM json_bug_test WHERE payload->'array_field' @> '[3]';

-- Extract number field
SELECT (payload->>'number_field')::int FROM json_bug_test WHERE id = 1;
-- Result: 42
```

## How to Run

### Using NoETL API

```bash
# Register playbook
curl -X POST http://localhost:8082/api/catalog/register \
  -H "Content-Type: application/json" \
  -d '{
    "path": "tests/fixtures/playbooks/json_serialization_save/json_serialization_save",
    "content": "<base64_encoded_yaml>"
  }'

# Execute playbook
curl -X POST http://localhost:8082/api/execute \
  -H "Content-Type: application/json" \
  -d '{
    "path": "tests/fixtures/playbooks/json_serialization_save/json_serialization_save"
  }'
```

### Using Python Script

```bash
cd /Users/akuksin/projects/noetl/noetl && python3 -c "
import requests, base64
with open('tests/fixtures/playbooks/json_serialization_save/json_serialization_save.yaml', 'r') as f:
    content = f.read()
r = requests.post('http://localhost:8082/api/catalog/register', 
                  json={'path': 'tests/fixtures/playbooks/json_serialization_save/json_serialization_save',
                        'content': base64.b64encode(content.encode()).decode()})
print(r.status_code, r.text)
" && curl -X POST http://localhost:8082/api/execute \
  -H "Content-Type: application/json" \
  -d '{"path":"tests/fixtures/playbooks/json_serialization_save/json_serialization_save"}'
```

### Verify Results

```bash
# Query database
kubectl exec -n postgres deployment/postgres -- \
  psql -U demo -d demo_noetl -c \
  "SELECT * FROM public.json_bug_test;"
```

## Common Issues

### Issue: Table empty after execution

**Symptom**: Playbook completes but json_bug_test table has 0 rows

**Root Cause #1**: Wrong event name in case condition
- ❌ `when: "{{ event.name == 'call.done' }}"` - Wrong event
- ✅ `when: "{{ event.name == 'step.exit' }}"` - Correct event

**Root Cause #2**: Incorrect YAML structure
- ❌ `then: {sink:..., next:...}` - Dictionary format (worker expects list)
- ✅ `then: [- sink:..., - next:...]` - List format

**Fix**: Use `step.exit` event and list format for `then` block

### Issue: Template rendering error "undefined variable"

**Symptom**: Worker logs show "Template rendering failed: 'data' is undefined"

**Root Cause**: Accessing undefined template variable
- ❌ `{{ data.id }}` - `data` not in template context
- ✅ `{{ result.data }}` or `{{ response.data }}` - Correct context access

**Fix**: Use proper template context: `result`, `response`, `this`, or `workload`

### Issue: Postgres error "requires 'table' and mapping 'data'"

**Symptom**: Sink fails with schema validation error

**Root Cause**: Extra fields outside `tool:` structure
- ❌ Incorrect:
  ```yaml
  sink:
    tool:
      kind: postgres
      auth: "..."
      statement: "..."
    table: my_table  # Wrong! Outside tool block
    mode: insert     # Wrong! Not needed
  ```
- ✅ Correct:
  ```yaml
  sink:
    tool:
      kind: postgres
      auth: "..."
      statement: "..."
  ```

**Fix**: Keep only `tool:` block with `kind`, `auth`, `statement` fields

### Issue: SQL injection or malformed JSON

**Symptom**: Insert fails with syntax error or JSON parse error

**Root Cause**: Single quotes in JSON not escaped
- ❌ `'{{ result.data | tojson }}'::jsonb` - Breaks on strings with quotes
- ✅ `'{{ result.data | tojson | replace("'", "''") }}'::jsonb` - Escapes quotes

**Fix**: Use `replace("'", "''")` filter after `tojson`

## Template Context Variables

NoETL v2 provides these variables in template context:

- `{{ result }}` - Current step's tool output (full response object)
- `{{ response }}` - Alias for `result`
- `{{ this }}` - Alias for `result`
- `{{ workload }}` - Global workflow variables
- `{{ vars.var_name }}` - Extracted variables from previous steps
- `{{ step_name }}` - Previous step results by step name
- `{{ execution_id }}` - Current execution identifier
- `{{ event }}` - Current event object with `name` field

**Note**: `data` is NOT automatically defined - you must access it via `result.data` or `response.data`

## Related Tests

- [iterator_save_test](../iterator_save_test/) - Per-iteration sink execution
- [save_storage_test](../save_storage_test/) - Multiple storage backends
- [v2_postgres_test](../v2_postgres_test.yaml) - Basic postgres operations

## Technical Details

**NoETL Version**: v2 (event-driven architecture)
**Worker**: v2_worker_nats.py handles sink evaluation and execution
**Template Engine**: Jinja2 with custom filters
**Event Lifecycle**: `step.enter` → (tool execution) → `call.done` → `step.exit` → `command.completed`
**Sink Timing**: Evaluated during `step.exit` event after tool execution

## Validation

This playbook was fixed as part of debugging session on 2026-01-04:

**Original Issue**: Table empty despite successful execution
**Root Causes**: 
1. Used `call.done` event instead of `step.exit`
2. YAML structure used dict format instead of list
3. Template accessed undefined `data` variable directly
4. Extra fields (`table:`, `mode:`, `args:`) outside tool config

**Fixes Applied**:
1. Changed condition: `call.done` → `step.exit`
2. Fixed structure: `then: {sink:..., next:...}` → `then: [- sink:..., - next:...]`
3. Fixed template: `{{ data.id }}` → hardcoded `1`
4. Removed extra fields, kept only `tool:` block

**Verification**: Execution 532658732933578819 inserted JSONB data correctly

**Test Status**: ✅ PASSED
