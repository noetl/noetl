# Vars Block Quick Reference

## When to Use

Use the `vars` block to **extract and store values AFTER step execution** from a step's result for reuse in subsequent steps.

Variables are stored in the `transient` database table and accessed via:
- **Template syntax**: `{{ vars.var_name }}` in playbook YAML
- **REST API**: `/api/vars/{execution_id}` for external access

For **BEFORE execution** variables, use:
- `workload:` section for global variables
- `args:` at step level for step-specific inputs
- `args:` in `next:` block to pass values to next step

## REST API Access

**GET all variables**:
```bash
GET /api/vars/{execution_id}
```

**GET single variable**:
```bash
GET /api/vars/{execution_id}/{var_name}
```

**SET variables**:
```bash
POST /api/vars/{execution_id}
Content-Type: application/json

{
  "variables": {"my_var": "value"},
  "var_type": "user_defined",
  "source_step": "external_system"
}
```

See `variables_feature_design.md` for complete API documentation.

## Syntax

```yaml
- step: step_name
  tool: <action_type>
  args:                      # ← BEFORE execution (optional)
    input_var: "{{ workload.value }}"
  # ... tool configuration ...
  vars:                      # ← AFTER execution (optional)
    variable_name: "{{ result.field }}"
    another_var: "{{ result.nested.value }}"
```

## Template Namespaces

| Context | Template | When Available | Description |
|---------|----------|----------------|-------------|
| **BEFORE** | `{{ workload.field }}` | Always | Global variables from workload section |
| **BEFORE** | `{{ args.field }}` | In step code | Input arguments passed to step |
| **BEFORE** | `{{ step_name.field }}` | After step_name executes | Direct access to previous step result |
| **AFTER** | `{{ result.field }}` | In vars block | Current step's result |
| **AFTER** | `{{ vars.var_name }}` | After vars extraction | Stored extracted variable |
| **ANYTIME** | `{{ execution_id }}` | Always | System execution identifier |
| **ANYTIME** | `{{ payload.field }}` | Always | CLI --payload values |

## Common Patterns

### Extract from Database Query

```yaml
- step: fetch_user
  tool:
    kind: postgres
    query: "SELECT user_id, email, status FROM users WHERE id = 123"
  vars:
    user_id: "{{ result[0].user_id }}"
    email: "{{ result[0].email }}"
    is_active: "{{ result[0].status == 'active' }}"
```

### Extract from Python Function

```yaml
- step: calculate
  tool:
    kind: python
    libs: {}
    args: {}
    code: |
      # Pure Python code - no imports, no def main()
      result = {"status": "success", "data": {"total": 100, "average": 25.5, "count": 4}}
  vars:
    total_amount: "{{ result.data.total }}"
    avg_value: "{{ result.data.average }}"
    record_count: "{{ result.data.count }}"
```

### Extract from HTTP Response

```yaml
- step: api_call
  tool:
    kind: http
    method: GET
    endpoint: "https://api.example.com/data"
  vars:
    response_status: "{{ result.status }}"
    first_item_id: "{{ result.data[0].id }}"
    total_records: "{{ result.data | length }}"
```

### Extract Array Elements

```yaml
- step: fetch_list
  tool:
    kind: postgres
    query: "SELECT name, value FROM items ORDER BY priority LIMIT 5"
  vars:
    first_name: "{{ result[0].name }}"
    second_name: "{{ result[1].name }}"
    all_names: "{{ result | map(attribute='name') | list }}"
    name_count: "{{ result | length }}"
```

### Use Extracted Variables

```yaml
- step: send_notification
  tool:
    kind: http
    method: POST
    endpoint: "{{ vars.api_endpoint }}"
    payload:
    user_id: "{{ vars.user_id }}"
    email: "{{ vars.email }}"
    total: "{{ vars.total_amount }}"
    message: "User {{ vars.user_id }} processed {{ vars.record_count }} records"
```

### Combine with Workload Variables

```yaml
workload:
  environment: production
  notification_url: "https://notify.example.com"

workflow:
- step: process_data
  tool:
    kind: python
    code: |
      def main(env):
        return {"processed": 100, "env": env}
  args:
    env: "{{ workload.environment }}"
  vars:
    processed_count: "{{ result.processed }}"
  
- step: notify
  tool:
    kind: http
    method: POST
    endpoint: "{{ workload.notification_url }}"
    payload:
    environment: "{{ workload.environment }}"
    count: "{{ vars.processed_count }}"
```

## Jinja2 Filters

Use Jinja2 filters to transform extracted values:

```yaml
vars:
  # String operations
  upper_name: "{{ result.name | upper }}"
  lower_email: "{{ result.email | lower }}"
  trimmed: "{{ result.text | trim }}"
  
  # Number operations
  rounded: "{{ result.value | round(2) }}"
  absolute: "{{ result.delta | abs }}"
  
  # List operations
  first_item: "{{ result.items | first }}"
  last_item: "{{ result.items | last }}"
  item_count: "{{ result.items | length }}"
  sorted_items: "{{ result.items | sort }}"
  
  # Object operations
  keys_list: "{{ result.metadata | list }}"
  has_field: "{{ 'user_id' in result }}"
  
  # Type conversion
  as_string: "{{ result.count | string }}"
  as_int: "{{ result.value | int }}"
  as_float: "{{ result.amount | float }}"
  
  # Default values
  with_fallback: "{{ result.optional_field | default('fallback_value') }}"
```

## Conditional Extraction

```yaml
vars:
  # Extract based on condition
  status: "{{ 'active' if result.count > 0 else 'inactive' }}"
  
  # Ternary expression
  level: "{{ 'high' if result.value > 100 else 'low' }}"
  
  # Boolean evaluation
  is_valid: "{{ result.status == 'success' and result.code == 200 }}"
  
  # Null handling
  safe_value: "{{ result.optional | default(0) }}"
```

## Best Practices

### ✅ Do

- Use descriptive variable names: `user_email` not `e`
- Extract specific fields needed by subsequent steps
- Use filters to transform data at extraction time
- Document complex extractions with step descriptions

### ❌ Avoid

- Extracting entire result objects (use direct step references instead)
- Deep nesting: `{{ result.a.b.c.d.e }}` (consider flattening)
- Complex calculations in templates (use Python steps instead)
- Extracting variables never used in subsequent steps

## Debugging

**Check variable storage**:
```sql
SELECT var_name, var_value, source_step, created_at
FROM transient
WHERE execution_id = <your_execution_id>
ORDER BY created_at;
```

**View worker logs** (shows loaded variables):
```bash
kubectl logs -n noetl deployment/noetl-worker --tail=100 | grep "Loaded.*variables"
```

**Check orchestrator logs** (shows vars processing):
```bash
kubectl logs -n noetl deployment/noetl-server --tail=100 | grep "Processing vars block"
```

## Error Handling

**Template rendering errors** are logged but don't fail the step:
```
ERROR Failed to render var 'user_id': 'result' is undefined
```

**Common issues**:
- `'result' is undefined` - vars block executed at wrong time (internal error)
- `KeyError: 'field_name'` - Field doesn't exist in result
- `TypeError: 'NoneType' object` - Result is null

**Solutions**:
- Use default filter: `{{ result.field | default('fallback') }}`
- Check field existence: `{{ result.field if 'field' in result else 'default' }}`
- Validate step result structure before extraction

## Reference Documentation

- **Implementation Summary**: `docs/vars_block_implementation_summary.md`
- **Feature Design**: `docs/variables_feature_design.md`
- **DSL Specification**: `doc./spec.md`
- **Test Examples**: `tests/fixtures/playbooks/vars_test/test_vars_block.yaml`
