---
sidebar_position: 12
---

# Regression Testing

NoETL includes a self-testing framework that uses playbook composition to validate all test playbooks and prevent regressions. The framework leverages NoETL's native features rather than external testing tools.

## Overview

The regression testing framework uses:
- **`tool: playbook`** - Execute playbooks from within playbooks
- **Event log queries** - Validate execution results via `noetl.event` table
- **Postgres sink** - Store test results in database
- **Jinja2 templating** - Access execution results dynamically

This creates a self-contained, database-backed test suite that runs entirely within NoETL's architecture.

## Architecture

### Event-Driven Design

NoETL's asynchronous, event-driven architecture requires specific testing patterns:

1. **Each step executes in isolation** - Workers pull jobs independently
2. **Server coordinates via events** - Command → event → command flow
3. **`tool: playbook` returns immediately** - Doesn't wait for sub-playbook completion
4. **Validation queries the event log** - Final status determined from events

### Three-Step Pattern

```yaml
# 1. Execute test playbook (async)
- step: test_playbook
  tool: playbook
  path: tests/fixtures/playbooks/hello_world
  next:
    - step: wait_for_completion

# 2. Wait for nested execution
- step: wait_for_completion
  tool: python
  code: |
    async def main():
        import asyncio
        await asyncio.sleep(3)
        return {"status": "success"}
  next:
    - step: validate_results

# 3. Query events and validate
- step: validate_results
  tool: postgres
  auth: "{{ workload.pg_auth }}"
  command: |
    WITH final_event AS (
      SELECT status, event_type
      FROM noetl.event
      WHERE execution_id = {{ test_playbook.execution_id }}
      ORDER BY event_id DESC LIMIT 1
    ),
    event_stats AS (
      SELECT COUNT(*) as event_count
      FROM noetl.event
      WHERE execution_id = {{ test_playbook.execution_id }}
    )
    SELECT 
      f.status as final_status,
      s.event_count,
      CASE WHEN f.status = 'COMPLETED' AND s.event_count >= 3 
           THEN true ELSE false END as test_passed
    FROM final_event f, event_stats s
  sink:
    tool: postgres
    table: noetl_test.regression_results
    data:
      test_run_id: "{{ workload.test_run_id }}"
      status: "{{ result.data.command_0.rows[0].final_status }}"
      test_passed: "{{ result.data.command_0.rows[0].test_passed }}"
```

## Quick Start

### Setup Test Schema

Create the test database schema:

```bash
task test:regression:setup
```

This creates:
- `noetl_test.regression_results` - Individual test results
- `noetl_test.regression_summary` - Test run summaries
- `noetl_test.expected_results` - Baseline expectations

### Run Tests

Execute the regression test suite:

```bash
# Full flow (setup + run + results)
task test:regression:full

# Just run tests
task test:regression:run

# View latest results
task test:regression:results
```

### Via CLI

```bash
# Register master test playbook
noetl register tests/fixtures/playbooks/regression_test/master_regression_test.yaml \
  --host localhost --port 8082

# Execute test suite
noetl execute playbook tests/fixtures/playbooks/regression_test/master_regression_test \
  --host localhost --port 8082 \
  --payload '{"pg_auth": "pg_k8s"}' --merge --json
```

### Via API

```bash
curl -X POST "http://localhost:8082/api/run/playbook" \
  -H "Content-Type: application/json" \
  -d '{
    "path": "tests/fixtures/playbooks/regression_test/master_regression_test",
    "parameters": {"pg_auth": "pg_k8s"},
    "merge": true
  }'
```

## Database Schema

### regression_results

Stores individual test execution results:

```sql
CREATE TABLE noetl_test.regression_results (
  test_run_id BIGINT NOT NULL,
  test_timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
  playbook_name VARCHAR(255) NOT NULL,
  playbook_path VARCHAR(500) NOT NULL,
  category VARCHAR(100),
  execution_id BIGINT,
  status VARCHAR(50) NOT NULL,
  execution_time_ms INTEGER,
  step_count INTEGER,
  error_message TEXT,
  validation_passed BOOLEAN,
  validation_errors JSONB,
  expected_status VARCHAR(50),
  actual_events JSONB,
  test_passed BOOLEAN NOT NULL,
  PRIMARY KEY (test_run_id, playbook_name)
);
```

### regression_summary

Aggregated test run statistics:

```sql
CREATE TABLE noetl_test.regression_summary (
  test_run_id BIGINT PRIMARY KEY,
  test_timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
  total_tests INTEGER NOT NULL,
  passed_tests INTEGER NOT NULL,
  failed_tests INTEGER NOT NULL,
  skipped_tests INTEGER NOT NULL,
  total_execution_time_ms INTEGER,
  success_rate DECIMAL(5,2),
  categories_tested TEXT[],
  git_commit VARCHAR(100),
  test_config JSONB
);
```

## Querying Results

### View Latest Results

```sql
SELECT 
  test_run_id,
  playbook_name,
  test_passed,
  status,
  step_count,
  execution_id
FROM noetl_test.regression_results
ORDER BY test_timestamp DESC
LIMIT 20;
```

### Test Summary

```sql
SELECT 
  test_run_id,
  total_tests,
  passed_tests,
  failed_tests,
  success_rate,
  test_timestamp
FROM noetl_test.regression_summary
ORDER BY test_timestamp DESC
LIMIT 10;
```

### Find Failures

```sql
SELECT 
  playbook_name,
  status,
  execution_id,
  error_message,
  test_timestamp
FROM noetl_test.regression_results
WHERE test_passed = false
ORDER BY test_timestamp DESC;
```

### Compare Test Runs

```sql
SELECT 
  test_run_id,
  playbook_name,
  test_passed,
  status,
  step_count
FROM noetl_test.regression_results
WHERE test_run_id IN (
  SELECT test_run_id 
  FROM noetl_test.regression_summary 
  ORDER BY test_timestamp DESC 
  LIMIT 2
)
ORDER BY test_run_id DESC, playbook_name;
```

## Adding New Tests

### Basic Test Pattern

Add a new test to `master_regression_test.yaml`:

```yaml
# 1. Execute test playbook
- step: test_my_playbook
  desc: "Test my_playbook"
  tool: playbook
  path: tests/fixtures/playbooks/my_category/my_playbook
  next:
    - step: wait_for_my_playbook

# 2. Wait for completion
- step: wait_for_my_playbook
  desc: "Wait for my_playbook to complete"
  tool: python
  code: |
    async def main():
        import asyncio
        await asyncio.sleep(3)  # Adjust as needed
        return {"status": "success"}
  next:
    - step: validate_my_playbook

# 3. Validate and save
- step: validate_my_playbook
  desc: "Validate my_playbook results"
  tool: postgres
  auth: "{{ workload.pg_auth }}"
  command: |
    WITH final_event AS (
      SELECT status, event_type
      FROM noetl.event
      WHERE execution_id = {{ test_my_playbook.execution_id }}
      ORDER BY event_id DESC LIMIT 1
    ),
    event_stats AS (
      SELECT COUNT(*) as event_count
      FROM noetl.event
      WHERE execution_id = {{ test_my_playbook.execution_id }}
    )
    SELECT 
      '{{ test_my_playbook.execution_id }}' as execution_id,
      'my_playbook' as test_name,
      f.status as final_status,
      s.event_count,
      CASE WHEN f.status = 'COMPLETED' AND s.event_count >= 2 
           THEN true ELSE false END as test_passed
    FROM final_event f, event_stats s
  sink:
    tool: postgres
    auth: "{{ workload.pg_auth }}"
    table: noetl_test.regression_results
    data:
      test_run_id: "{{ workload.test_run_id }}"
      playbook_name: "{{ result.data.command_0.rows[0].test_name }}"
      playbook_path: tests/fixtures/playbooks/my_category/my_playbook
      category: my_category
      execution_id: "{{ result.data.command_0.rows[0].execution_id }}"
      status: "{{ result.data.command_0.rows[0].final_status }}"
      step_count: "{{ result.data.command_0.rows[0].event_count }}"
      validation_passed: "{{ result.data.command_0.rows[0].test_passed }}"
      expected_status: completed
      test_passed: "{{ result.data.command_0.rows[0].test_passed }}"
  next:
    - step: next_test_or_summary
```

### Adjusting Wait Time

The `asyncio.sleep()` duration depends on playbook complexity:

- **Simple playbooks** (1-2 steps): 2-3 seconds
- **Medium playbooks** (3-5 steps): 3-5 seconds
- **Complex playbooks** (5+ steps): 5-10 seconds
- **External API calls**: 10-15 seconds

### Custom Validation

Extend validation logic with additional checks:

```yaml
command: |
  WITH final_event AS (
    SELECT status, event_type, error
    FROM noetl.event
    WHERE execution_id = {{ test_playbook.execution_id }}
    ORDER BY event_id DESC LIMIT 1
  ),
  event_stats AS (
    SELECT 
      COUNT(*) as event_count,
      COUNT(*) FILTER (WHERE error IS NOT NULL) as error_count,
      COUNT(*) FILTER (WHERE event_type = 'action_completed') as completed_actions
    FROM noetl.event
    WHERE execution_id = {{ test_playbook.execution_id }}
  )
  SELECT 
    f.status as final_status,
    s.event_count,
    s.error_count,
    s.completed_actions,
    CASE 
      WHEN f.status = 'COMPLETED' 
       AND s.event_count >= 5
       AND s.error_count = 0
       AND s.completed_actions >= 3
      THEN true 
      ELSE false 
    END as test_passed
  FROM final_event f, event_stats s
```

## Troubleshooting

### Test Shows "unknown" Status

**Symptom**: Results show `status: 'unknown'` and `step_count: 0`

**Cause**: Validation queried events before nested playbook completed

**Solution**: Increase wait time:
```yaml
await asyncio.sleep(5)  # Increase from 3 to 5 seconds
```

### Wrong Execution ID

**Symptom**: Query returns no results or wrong data

**Cause**: Incorrect execution ID reference

**Fix**: Verify correct step name in query:
```yaml
WHERE execution_id = {{ test_playbook.execution_id }}
```

### Postgres Result Structure

**Symptom**: Template errors accessing result fields

**Cause**: Postgres plugin wraps results in `command_0.rows` structure

**Fix**: Always use proper path:
```yaml
data:
  field: "{{ result.data.command_0.rows[0].field_name }}"
```

### Vars Not Propagating

**Symptom**: Sink data has empty or missing values

**Cause**: `vars:` block extractions don't always propagate to sink

**Solution**: Reference result directly:
```yaml
sink:
  data:
    value: "{{ result.data.command_0.rows[0].value }}"  # Direct access
```

### JSON Column Errors

**Symptom**: `invalid input syntax for type json`

**Cause**: Python `None` becomes string `'None'` instead of SQL `NULL`

**Fix**: Remove optional JSONB fields or use proper null:
```yaml
data:
  optional_field: null  # JSON null, not Python None
```

## Best Practices

### 1. Consistent Naming

Use consistent step naming patterns:
- `test_{playbook_name}` - Execute playbook
- `wait_for_{playbook_name}` - Wait step
- `validate_{playbook_name}` - Validation and sink

### 2. Parameterize Tests

Use workload variables for flexibility:

```yaml
workload:
  test_run_id: "{{ execution_id }}"
  pg_auth: pg_local
  wait_time: 3
  min_events: 3
```

### 3. Error Handling

Include error checking in validation:

```yaml
SELECT 
  f.status,
  f.error,
  CASE 
    WHEN f.error IS NOT NULL THEN false
    WHEN f.status != 'COMPLETED' THEN false
    ELSE true
  END as test_passed
FROM final_event f
```

### 4. Modular Design

Break large test suites into categories:

```yaml
workflow:
  - step: start
    next:
      - step: test_basic_category
      - step: test_control_flow_category
      - step: test_data_processing_category
```

### 5. Summary Generation

Always generate summary at the end:

```yaml
- step: generate_summary
  tool: postgres
  auth: "{{ workload.pg_auth }}"
  command: |
    INSERT INTO noetl_test.regression_summary (
      test_run_id, total_tests, passed_tests, 
      failed_tests, success_rate
    )
    SELECT 
      {{ workload.test_run_id }},
      COUNT(*),
      COUNT(*) FILTER (WHERE test_passed = true),
      COUNT(*) FILTER (WHERE test_passed = false),
      ROUND(100.0 * COUNT(*) FILTER (WHERE test_passed = true) / NULLIF(COUNT(*), 0), 2)
    FROM noetl_test.regression_results
    WHERE test_run_id = {{ workload.test_run_id }}
```

## Current Coverage

The framework currently tests:

1. **hello_world** - Basic playbook execution
2. **test_start_with_action** - Workflows starting with actions
3. **test_vars_simple** - Variable handling

**Target**: Expand to all 56 playbooks in `tests/fixtures/playbooks/`

## Advanced Topics

### Parallel Test Execution

Use array syntax in `next` to run tests concurrently:

```yaml
- step: start_tests
  next:
    - step: test_playbook_1
    - step: test_playbook_2
    - step: test_playbook_3
```

All three tests will execute in parallel, improving performance.

### Conditional Testing

Skip tests based on conditions:

```yaml
- step: check_environment
  tool: python
  code: |
    async def main():
        import os
        return {
            "status": "success",
            "data": {"skip_slow_tests": os.getenv("FAST_MODE") == "true"}
        }
  next:
    - when: "{{ not result.data.skip_slow_tests }}"
      then:
        - step: test_slow_playbook
    - step: continue_tests
```

### Expected Results Baseline

Store expected results for comparison:

```sql
INSERT INTO noetl_test.expected_results 
  (playbook_name, expected_status, min_events, max_duration_ms)
VALUES
  ('hello_world', 'COMPLETED', 3, 1000),
  ('test_vars_simple', 'COMPLETED', 2, 500);
```

Then validate against baseline:

```yaml
command: |
  SELECT 
    r.playbook_name,
    r.status = e.expected_status as status_match,
    r.step_count >= e.min_events as event_count_ok
  FROM noetl_test.expected_results e
  LEFT JOIN (
    SELECT status, step_count, playbook_name
    FROM noetl.event
    WHERE execution_id = {{ test_playbook.execution_id }}
  ) r ON r.playbook_name = e.playbook_name
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Regression Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup NoETL cluster
        run: |
          task kind-create-cluster
          task deploy-postgres
          task deploy-noetl
      
      - name: Run regression tests
        run: task test:regression:full
      
      - name: Check results
        run: |
          # Query test results and fail if any tests failed
          kubectl exec -n postgres $(kubectl get pod -n postgres -l app=postgres -o name) -- \
            psql -U demo -d demo_noetl -t -c \
            "SELECT COUNT(*) FROM noetl_test.regression_results WHERE test_passed = false" \
            | grep -q "^0$" || exit 1
```

## Files and Locations

- **Schema**: `tests/fixtures/playbooks/regression_test/create_test_schema.yaml`
- **Master Test**: `tests/fixtures/playbooks/regression_test/master_regression_test.yaml`
- **Documentation**: `tests/fixtures/playbooks/regression_test/README.md`
- **Tasks**: `ci/taskfile/test.yml`

## See Also

- [Playbook DSL Reference](./dsl_spec.md)
- [Event-Driven Architecture](./playbook_execution_flow.md)
- [Postgres Plugin](./database_refactoring_summary.md)
- [Task Automation](./development.md#task-automation)
