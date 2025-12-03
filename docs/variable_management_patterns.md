# Variable Management Patterns in NoETL

## Overview

NoETL provides different mechanisms for passing variables at different stages of workflow execution. Understanding WHEN variables are available is key to effective playbook design.

## Variable Lifecycle

```
BEFORE Execution → Step Executes → AFTER Execution
     ↓                                    ↓
  workload:                            vars:
  args:                                result
                                       step_name.field
```

## BEFORE Execution (Input Variables)

### 1. Global Variables - `workload:` Section

**When**: Defined once, available to all steps throughout workflow execution
**Use Case**: Configuration, constants, shared values

```yaml
workload:
  api_key: "abc123"
  environment: "production"
  base_url: "{{ payload.url }}"  # Can reference CLI payload

workflow:
  - step: call_api
    tool: http
    endpoint: "{{ workload.base_url }}/data"
    headers:
      Authorization: "Bearer {{ workload.api_key }}"
      X-Environment: "{{ workload.environment }}"
```

### 2. Step Input Arguments - `args:` at Step Level

**When**: Evaluated and passed to step immediately before execution
**Use Case**: Step-specific inputs, computed values from previous steps

```yaml
- step: process_data
  tool: python
  args:                                    # ← Evaluated BEFORE step runs
    input_value: 100
    multiplier: "{{ workload.retry_count }}"
    previous_total: "{{ fetch_data.total }}"
    user_email: "{{ vars.email }}"
  code: |
    def main(input_value, multiplier, previous_total, user_email):
        # All args are available as function parameters
        result = input_value * multiplier + previous_total
        return {"result": result, "user": user_email}
```

### 3. Next Step Arguments - `args:` in `next:` Block

**When**: Evaluated when routing to next step, passed before next step executes
**Use Case**: Conditional flow with different inputs per branch

```yaml
- step: decide
  tool: python
  code: |
    def main():
        return {"status": "success", "attempt": 1, "should_retry": True}
  next:
    - when: "{{ result.should_retry }}"
      then:
        - step: retry_action
      args:                                # ← Passed to retry_action BEFORE it runs
        attempt_number: "{{ result.attempt }}"
        max_attempts: 3
        reason: "timeout"
    - when: "{{ not result.should_retry }}"
      then:
        - step: complete
```

## AFTER Execution (Extract from Result)

### 1. Vars Block - `vars:` at Step Level

**When**: Evaluated after step completes, stored for use in any subsequent step
**Use Case**: Extract complex values once, reuse multiple times; simplify templates

```yaml
- step: fetch_users
  tool: postgres
  query: "SELECT user_id, email, created_at FROM users WHERE active = true LIMIT 10"
  vars:                                    # ← Evaluated AFTER query completes
    first_user_id: "{{ result[0].user_id }}"
    first_email: "{{ result[0].email }}"
    user_count: "{{ result | length }}"
    all_emails: "{{ result | map(attribute='email') | list }}"
  next:
    - step: send_notifications

- step: send_notifications
  tool: http
  method: POST
  endpoint: "https://api.example.com/notify"
  payload:
    user_id: "{{ vars.first_user_id }}"   # Cleaner than result[0].user_id
    email: "{{ vars.first_email }}"
    total: "{{ vars.user_count }}"
    all_emails: "{{ vars.all_emails }}"
```

**Benefits of vars:**
- Simplifies complex Jinja expressions
- Reuse extracted values in multiple steps
- Clear naming for important values
- Works across conditional branches
- Stored in vars_cache for inspection

### 2. Direct Step Access - `{{ step_name.field }}`

**When**: Available immediately after step completes, no extraction needed
**Use Case**: Simple one-time access to previous step result

```yaml
- step: calculate
  tool: python
  code: |
    def main():
        return {"total": 100, "count": 5, "status": "ok"}
  next:
    - step: report

- step: report
  tool: python
  args:
    # Direct access - no vars needed for simple cases
    total: "{{ calculate.total }}"
    average: "{{ calculate.total / calculate.count }}"
    status: "{{ calculate.status }}"
  code: |
    def main(total, average, status):
        return f"Report: {status} - Total: {total}, Avg: {average}"
```

**When to use vars vs direct access:**
- Use `vars:` when value is used in **multiple steps** or **complex extraction**
- Use direct access (`{{ step_name.field }}`) for **one-time simple access**

## Loop and Pagination Patterns

Variables extracted in iteration N are available in iteration N+1:

```yaml
- step: paginate
  tool: http
  method: GET
  url: "https://api.example.com/data"
  params:
    page: 1
  loop:
    pagination:
      type: response_based
      continue_while: "{{ response.data.hasMore }}"
      next_page:
        params:
          # Use vars from previous iteration
          page: "{{ (vars.current_page | int) + 1 }}"
      merge_strategy: append
      merge_path: data.items
  vars:
    # Extracted each iteration
    current_page: "{{ result.data.page }}"
    total_fetched: "{{ result.data.items | length }}"
```

## Template Namespace Quick Reference

| Template | Timing | Scope | Example |
|----------|--------|-------|---------|
| `{{ workload.field }}` | BEFORE | Global | `{{ workload.api_key }}` |
| `{{ args.field }}` | BEFORE | Step input | `{{ args.user_id }}` (in Python code) |
| `{{ vars.var_name }}` | AFTER | Extracted | `{{ vars.email }}` |
| `{{ result.field }}` | AFTER | Current step | `{{ result.total }}` (in vars block) |
| `{{ step_name.field }}` | AFTER | Previous step | `{{ calculate.total }}` |
| `{{ execution_id }}` | ANYTIME | System | `{{ execution_id }}` |
| `{{ payload.field }}` | ANYTIME | CLI input | `{{ payload.user_id }}` |

## Best Practices

1. **Use workload for configuration**: API keys, base URLs, environment settings
2. **Use args for computed inputs**: Pass calculated values to steps
3. **Use vars for reusable extractions**: Extract once, use many times
4. **Use direct access for simple cases**: Avoid vars overhead for one-time use
5. **Name variables clearly**: `user_email` not `e`, `total_count` not `tc`
6. **Extract early, use late**: Extract in first step that has the value
7. **Avoid deep nesting in templates**: Use vars to flatten complex expressions

## Common Patterns

### Pattern 1: Configuration with Override
```yaml
workload:
  default_timeout: 30
  api_url: "{{ payload.api_url | default('https://api.example.com') }}"
```

### Pattern 2: Extract and Transform
```yaml
- step: fetch
  tool: postgres
  query: "SELECT id, name, created_at FROM users"
  vars:
    user_ids: "{{ result | map(attribute='id') | list }}"
    user_names: "{{ result | map(attribute='name') | join(', ') }}"
    total_users: "{{ result | length }}"
```

### Pattern 3: Conditional Routing with Args
```yaml
- step: check
  tool: python
  code: |
    def main():
        return {"threshold": 100, "actual": 150, "exceeds": True}
  next:
    - when: "{{ result.exceeds }}"
      then:
        - step: alert
      args:
        threshold: "{{ result.threshold }}"
        actual: "{{ result.actual }}"
```

### Pattern 4: Multi-Step Variable Flow
```yaml
workload:
  base_id: 1000

- step: generate
  tool: python
  args:
    base: "{{ workload.base_id }}"
  code: |
    def main(base):
        return {"generated_id": base + 42}
  vars:
    new_id: "{{ result.generated_id }}"

- step: use_both
  tool: python
  args:
    original: "{{ workload.base_id }}"
    generated: "{{ vars.new_id }}"
  code: |
    def main(original, generated):
        return f"Original: {original}, Generated: {generated}"
```

## See Also

- [DSL Specification](../docs/dsl_spec.md) - Complete DSL reference
- [Vars Block Quick Reference](../documentation/docs/reference/vars_block_quick_reference.md) - Vars syntax
- [Variable Lifecycle Example](../tests/fixtures/playbooks/examples/variable_lifecycle_example.yaml) - Working example
