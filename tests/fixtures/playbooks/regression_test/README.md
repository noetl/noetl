# NoETL Native Regression Testing

Using NoETL's own playbook composition features to test all playbooks - a self-testing framework!

## Overview

Instead of external test frameworks, this approach uses NoETL's native capabilities:
- **`tool: playbook`** - Execute other playbooks from within a playbook
- **`workbook` section** - Reusable analysis tasks
- **`sink: postgres`** - Store test results in database
- **Jinja2 templating** - Access sub-playbook results

This creates a **self-contained, database-backed test suite** that runs entirely within NoETL.

## Architecture

```
Master Test Playbook (master_regression_test.yaml)
├── Execute test playbook 1 (tool: playbook)
├── Analyze result (workbook task)
├── Save to postgres (sink)
├── Execute test playbook 2
├── Analyze result
├── Save to postgres
├── ...
└── Generate summary report
```

**Test Results Database:**
- `noetl_test.regression_results` - Individual test results
- `noetl_test.regression_summary` - Test run summaries
- `noetl_test.expected_results` - Baseline expectations

## Quick Start

### 1. Setup test schema

```bash
task test-regression-setup
# Creates noetl_test schema and tables
```

### 2. Run regression tests

```bash
task test-regression-run
# Executes master_regression_test playbook
```

### 3. View results

```bash
task test-regression-view
# Shows latest test results from database
```

### One-step execution

```bash
task test-regression-full
# Setup + Run in one command
```

## Task Commands

```bash
# Setup
task test:regression:setup        # Create test schema
# Alias: task trs

# Execution
task test:regression:run          # Run master test playbook
# Alias: task trr

task test:regression:full         # Setup + Run
# Alias: task trf

# Results
task test:regression:results      # View test results
# Alias: task trv, task test-regression-view
```

## Master Test Playbook

**File:** `tests/fixtures/playbooks/regression_test/master_regression_test.yaml`

### Structure

```yaml
workload:
  test_run_id: "{{ execution_id }}"  # Unique test run ID
  test_config:
    playbooks:
      basic:
        - name: hello_world
          path: tests/fixtures/playbooks/hello_world/hello_world
          expected_status: completed
          min_steps: 3
          required_steps: [start, test_step, end]

workbook:
  - name: analyze_test_result
    tool: python
    code: |
      # Validates execution against expectations
      # Returns pass/fail result

workflow:
  - step: test_hello_world
    tool: playbook
    path: tests/fixtures/playbooks/hello_world/hello_world
    return_step: analyze_hello_world
  
  - step: analyze_hello_world
    type: workbook
    name: analyze_test_result
    data:
      test_name: hello_world
      expected_status: completed
      actual_status: "{{ test_hello_world.status }}"
      actual_events: "{{ test_hello_world.events }}"
    sink:
      tool: postgres
      table: noetl_test.regression_results
      data:
        test_run_id: "{{ workload.test_run_id }}"
        playbook_name: hello_world
        test_passed: "{{ result.data.test_passed }}"
        # ... all test data
```

### Key Features

1. **Playbook Execution** - `tool: playbook` runs sub-playbooks
2. **Result Analysis** - Workbook task validates outcomes
3. **Database Storage** - Sink saves results to postgres
4. **Template Access** - `{{ test_hello_world.status }}` accesses sub-playbook data
5. **Summary Generation** - SQL aggregates results

## Test Result Schema

### regression_results Table

```sql
CREATE TABLE noetl_test.regression_results (
  test_run_id BIGINT NOT NULL,           -- Master playbook execution_id
  playbook_name VARCHAR(255) NOT NULL,   -- Test name
  playbook_path VARCHAR(500) NOT NULL,   -- Playbook path
  category VARCHAR(100),                 -- Test category
  execution_id BIGINT,                   -- Sub-playbook execution_id
  status VARCHAR(50) NOT NULL,           -- Execution status
  step_count INTEGER,                    -- Number of steps
  validation_passed BOOLEAN,             -- Validation rules passed
  validation_errors JSONB,               -- Validation error details
  expected_status VARCHAR(50),           -- Expected status
  actual_events JSONB,                   -- All execution events
  test_passed BOOLEAN NOT NULL,          -- Overall pass/fail
  PRIMARY KEY (test_run_id, playbook_name)
);
```

### regression_summary Table

```sql
CREATE TABLE noetl_test.regression_summary (
  test_run_id BIGINT PRIMARY KEY,        -- Master execution_id
  total_tests INTEGER NOT NULL,          -- Total test count
  passed_tests INTEGER NOT NULL,         -- Passed count
  failed_tests INTEGER NOT NULL,         -- Failed count
  success_rate DECIMAL(5,2),             -- % passed
  categories_tested TEXT[],              -- Categories tested
  test_config JSONB,                     -- Test configuration
  test_timestamp TIMESTAMP NOT NULL
);
```

## Querying Test Results

### Latest Test Run Summary

```bash
curl -X POST "http://localhost:8082/api/postgres/execute" \
  -H 'Content-Type: application/json' \
  -d '{
    "schema": "noetl_test",
    "query": "SELECT * FROM regression_summary ORDER BY test_timestamp DESC LIMIT 1"
  }' | jq .
```

### Failed Tests

```bash
curl -X POST "http://localhost:8082/api/postgres/execute" \
  -H 'Content-Type: application/json' \
  -d '{
    "schema": "noetl_test",
    "query": "SELECT playbook_name, status, validation_errors FROM regression_results WHERE test_run_id = (SELECT test_run_id FROM regression_summary ORDER BY test_timestamp DESC LIMIT 1) AND test_passed = false"
  }' | jq .
```

### Test History

```sql
SELECT 
  test_timestamp,
  total_tests,
  passed_tests,
  failed_tests,
  success_rate
FROM noetl_test.regression_summary
ORDER BY test_timestamp DESC
LIMIT 10;
```

### Flaky Tests

```sql
SELECT 
  playbook_name,
  COUNT(*) as total_runs,
  SUM(CASE WHEN test_passed THEN 1 ELSE 0 END) as passed,
  SUM(CASE WHEN NOT test_passed THEN 1 ELSE 0 END) as failed,
  ROUND(100.0 * SUM(CASE WHEN test_passed THEN 1 ELSE 0 END) / COUNT(*), 2) as pass_rate
FROM noetl_test.regression_results
GROUP BY playbook_name
HAVING COUNT(*) >= 5 AND pass_rate < 100
ORDER BY pass_rate ASC;
```

## Adding New Tests

### 1. Add to test_config in master playbook

```yaml
workload:
  test_config:
    playbooks:
      your_category:
        - name: my_new_test
          path: tests/fixtures/playbooks/my_category/my_new_test
          expected_status: completed
          min_steps: 4
          required_steps: [start, process, validate, end]
          requires_credentials:
            pg_auth: pg_k8s
```

### 2. Add workflow steps

```yaml
workflow:
  - step: test_my_new_test
    tool: playbook
    path: tests/fixtures/playbooks/my_category/my_new_test
    return_step: analyze_my_new_test
    data:
      pg_auth: "{{ workload.pg_auth | default('pg_k8s') }}"
    next:
      - step: analyze_my_new_test

  - step: analyze_my_new_test
    type: workbook
    name: analyze_test_result
    data:
      test_name: my_new_test
      expected_status: completed
      expected_min_steps: 4
      expected_step_names: [start, process, validate, end]
      actual_execution_id: "{{ test_my_new_test.execution_id }}"
      actual_status: "{{ test_my_new_test.status }}"
      actual_events: "{{ test_my_new_test.events }}"
    sink:
      tool: postgres
      auth:
        type: postgres
        credential: "{{ workload.pg_auth | default('pg_k8s') }}"
      table: noetl_test.regression_results
      data:
        test_run_id: "{{ workload.test_run_id }}"
        playbook_name: my_new_test
        playbook_path: tests/fixtures/playbooks/my_category/my_new_test
        category: your_category
        execution_id: "{{ test_my_new_test.execution_id }}"
        status: "{{ test_my_new_test.status }}"
        step_count: "{{ result.data.actual_step_count }}"
        validation_passed: "{{ result.data.validation_passed }}"
        validation_errors: "{{ result.data.validations.errors | tojson }}"
        expected_status: "{{ result.data.expected_status }}"
        actual_events: "{{ test_my_new_test.events | tojson }}"
        test_passed: "{{ result.data.test_passed }}"
    next:
      - step: next_test
```

## Validation Logic

The `analyze_test_result` workbook task validates:

1. **Status Match** - `actual_status == expected_status`
2. **Step Count** - `len(actual_events) >= expected_min_steps`
3. **Required Steps** - All `expected_step_names` present in events

### Example Validation

```python
validations = {
    'status_match': actual_status == expected_status,
    'step_count_ok': len(actual_events) >= expected_min_steps,
    'required_steps_present': True,
    'errors': []
}

if not validations['status_match']:
    validations['errors'].append(
        f"Status mismatch: expected '{expected_status}', got '{actual_status}'"
    )

test_passed = all([
    validations['status_match'],
    validations['step_count_ok'],
    validations['required_steps_present']
])
```

## Benefits of NoETL-Native Testing

### Self-Contained
- No external test frameworks needed
- Uses NoETL's own features to test itself
- Database-backed results for querying and analysis

### Observable
- All test executions visible in NoETL event log
- Detailed execution history in postgres
- Easy to debug failed tests

### Composable
- Tests are playbooks - can be composed, nested, reused
- Workbook tasks for common validation logic
- Template-based configuration

### Queryable
- SQL access to test history
- Track trends over time
- Identify flaky tests
- Custom reporting

### CI/CD Ready
- Single command execution: `task test-regression-full`
- Exit code reflects test results
- JSON output for parsing
- Can be integrated into any CI system

## Comparison: NoETL-Native vs Pytest

| Feature | NoETL-Native | Pytest |
|---------|-------------|--------|
| Test Definition | YAML playbook | Python code |
| Result Storage | PostgreSQL | Files/Console |
| Test Execution | NoETL engine | pytest runner |
| Validation | Python in workbook | pytest assertions |
| History Tracking | SQL queries | External tools |
| CI Integration | Task command | pytest command |
| Learning Curve | Know NoETL DSL | Know pytest framework |
| Debugging | NoETL logs + events | pytest output + pdb |

**Best Practice:** Use both!
- NoETL-native for production monitoring
- Pytest for development/debugging

## Development Workflow

### Daily Development

```bash
# 1. Make code changes
vim noetl/plugin/tools/duckdb/config.py

# 2. Build and deploy
task docker-build-noetl
task deploy-noetl

# 3. Run regression tests
task test-regression-run

# 4. Check results
task test-regression-view

# 5. If failures, investigate
# View execution details in NoETL
# Check worker/server logs
# Debug specific playbook
```

### Before Committing

```bash
# Full regression test
task test-regression-full

# Ensure all tests pass
task test-regression-view | grep "success_rate"
# Should show 100.00%
```

### Continuous Integration

```yaml
# .github/workflows/test.yml
- name: Run regression tests
  run: |
    task test-regression-full
    
    # Check if all tests passed
    SUCCESS_RATE=$(task test-regression-view | jq '.result[0].success_rate')
    if [ "$SUCCESS_RATE" != "100.00" ]; then
      echo "Tests failed!"
      exit 1
    fi
```

## Troubleshooting

### Test schema doesn't exist

```bash
task test-regression-setup
```

### Playbooks not registered

```bash
task register-all-test-playbooks
```

### Credentials missing

```bash
task register-test-credentials
```

### View execution details

```bash
# Get test_run_id from summary
EXEC_ID=<test_run_id>

# View execution events
curl "http://localhost:8082/api/execution/$EXEC_ID/events" | jq .
```

### Debug specific failed test

```bash
# Execute playbook manually
task playbook:local:execute PLAYBOOK=tests/fixtures/playbooks/path/to/failed_playbook

# Check logs
kubectl logs -n noetl deployment/noetl-worker -f
```

## Future Enhancements

- **Parallel test execution** - Use iterator with async mode
- **Test categories** - Run subset of tests
- **Expected results baseline** - Store in `expected_results` table
- **Diff reporting** - Compare against baseline
- **Performance tracking** - Add execution_time_ms
- **Alerting** - Send notifications on failures
- **Dashboard** - Grafana visualization of test trends
- **Auto-recovery** - Retry flaky tests

## Files

- `tests/fixtures/playbooks/regression_test/create_test_schema.yaml` - Schema setup
- `tests/fixtures/playbooks/regression_test/master_regression_test.yaml` - Master test playbook
- `ci/taskfile/test.yml` - Task automation (regression section)

## Summary

This approach demonstrates NoETL's power:
- **Self-testing** - Framework tests itself using its own features
- **Database-backed** - All results queryable with SQL
- **Composable** - Playbooks testing playbooks
- **Observable** - Full execution history

A truly **NoETL-native testing solution**! 🚀
