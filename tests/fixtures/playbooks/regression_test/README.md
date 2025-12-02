# NoETL Regression Testing Framework

Self-testing framework using NoETL's native playbook composition to validate all test playbooks and prevent regressions.

## Architecture & Design

### Core Concept

NoETL's **event-driven, asynchronous architecture** requires a specific testing approach:
- Each step executes in isolation on a worker
- Server coordinates via events (command → event → command → event)
- `tool: playbook` returns immediately with execution_id (doesn't wait for completion)
- Sub-playbook executes asynchronously in the background
- Validation must query the event log after completion

### Workflow Pattern

```yaml
# 1. Execute test playbook (async)
- step: test_playbook
  tool: playbook
  path: catalog/path/to/playbook
  next:
    - step: wait_for_completion

# 2. Wait for nested playbook to finish
- step: wait_for_completion
  tool: python
  code: |
    async def main():
        import asyncio
        await asyncio.sleep(3)  # Wait for nested execution
        return {"status": "success"}
  next:
    - step: validate_results

# 3. Query postgres for execution results
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
      playbook_name: "{{ result.data.command_0.rows[0].test_name }}"
      status: "{{ result.data.command_0.rows[0].final_status }}"
      test_passed: "{{ result.data.command_0.rows[0].test_passed }}"
```

### Key Design Principles

1. **Async Execution**: `tool: playbook` enqueues sub-playbook and returns immediately
2. **Wait Step**: Required delay to allow nested playbook to complete
3. **Event Log Query**: Validation queries `noetl.event` table for final status
4. **Postgres Result Structure**: Results are wrapped in `result.data.command_0.rows[0].*`
5. **Sink After Validation**: Save test results to `noetl_test.regression_results` table

### Database Schema

```sql
-- Individual test results
CREATE TABLE noetl_test.regression_results (
  test_run_id BIGINT NOT NULL,
  playbook_name VARCHAR(255) NOT NULL,
  execution_id BIGINT,
  status VARCHAR(50) NOT NULL,
  step_count INTEGER,
  test_passed BOOLEAN NOT NULL,
  validation_passed BOOLEAN,
  expected_status VARCHAR(50),
  test_timestamp TIMESTAMP DEFAULT NOW(),
  PRIMARY KEY (test_run_id, playbook_name)
);

-- Test run summaries
CREATE TABLE noetl_test.regression_summary (
  test_run_id BIGINT PRIMARY KEY,
  total_tests INTEGER NOT NULL,
  passed_tests INTEGER NOT NULL,
  failed_tests INTEGER NOT NULL,
  skipped_tests INTEGER NOT NULL,
  success_rate DECIMAL(5,2),
  test_timestamp TIMESTAMP DEFAULT NOW()
);
```

## Quick Start

### 1. Setup test schema

```bash
task test:regression:setup
```

Creates `noetl_test` schema with:
- `regression_results` - Individual test results
- `regression_summary` - Test run summaries  
- `expected_results` - Baseline expectations

### 2. Run regression tests

```bash
task test:regression:run
```

Executes `master_regression_test.yaml` which:
- Tests 3 playbooks: hello_world, test_start_with_action, test_vars_simple
- Validates execution status and step counts
- Saves results to database
- Generates summary report

### 3. View results

```bash
task test:regression:results
```

Queries latest test results from `noetl_test.regression_results`:

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

### 4. Complete flow

```bash
task test:regression:full
```

Runs setup + execute + display results in one command.

## Usage Examples

### Running Tests

**Via Task Command:**
```bash
# Setup and run
task test:regression:full

# Just run tests (if schema exists)
task test:regression:run

# View latest results
task test:regression:results
```

**Via CLI:**
```bash
# Register master test playbook
noetl register tests/fixtures/playbooks/regression_test/master_regression_test.yaml \
  --host localhost --port 8082

# Execute test suite
noetl execute playbook tests/fixtures/playbooks/regression_test/master_regression_test \
  --host localhost --port 8082 \
  --payload '{"pg_auth": "pg_k8s"}' --merge --json
```

**Via API:**
```bash
# Execute via HTTP API
curl -X POST "http://localhost:8082/api/run/playbook" \
  -H "Content-Type: application/json" \
  -d '{
    "path": "tests/fixtures/playbooks/regression_test/master_regression_test",
    "parameters": {"pg_auth": "pg_k8s"},
    "merge": true
  }'

# Query results directly
kubectl exec -n postgres <pod> -- psql -U demo -d demo_noetl -c \
  "SELECT * FROM noetl_test.regression_results ORDER BY test_timestamp DESC LIMIT 5"
```

### Reading Results

**Check test summary:**
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

**Find failing tests:**
```sql
SELECT 
  playbook_name,
  status,
  execution_id,
  test_timestamp
FROM noetl_test.regression_results
WHERE test_passed = false
ORDER BY test_timestamp DESC;
```

**Compare test runs:**
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

### 1. Pattern for Single Test

Add a new test to `master_regression_test.yaml`:

```yaml
- step: test_my_playbook
  desc: "Test my_playbook"
  tool: playbook
  path: tests/fixtures/playbooks/my_category/my_playbook
  next:
    - step: wait_for_my_playbook

- step: wait_for_my_playbook
  desc: "Wait for my_playbook to complete"
  tool: python
  code: |
    async def main():
        import asyncio
        await asyncio.sleep(3)  # Adjust wait time as needed
        return {"status": "success"}
  next:
    - step: validate_my_playbook

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

### 2. Adjusting Wait Time

The `asyncio.sleep(3)` provides a buffer for the nested playbook to complete:
- **Simple playbooks** (1-2 steps): 2-3 seconds
- **Complex playbooks** (5+ steps): 5-10 seconds
- **Playbooks with external calls**: 10-15 seconds

Monitor execution times and adjust as needed.

### 3. Custom Validation Logic

Modify the SQL validation query to check specific conditions:

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

**Cause**: Validation step queried events before nested playbook completed.

**Solution**: Increase wait time in the wait step:
```yaml
await asyncio.sleep(5)  # Increase from 3 to 5 seconds
```

### Test Shows 0 Event Count

**Cause**: Wrong execution_id or query ran too early.

**Fix**: Verify execution_id is correctly passed:
```yaml
WHERE execution_id = {{ test_playbook.execution_id }}  # Correct reference
```

### Postgres Result Structure Errors

**Cause**: Postgres plugin wraps results in `command_0.rows` structure.

**Fix**: Always access as:
```yaml
"{{ result.data.command_0.rows[0].field_name }}"
```

### Vars Not Available in Sink

**Cause**: `vars:` block extractions may not propagate to sink.

**Solution**: Reference result directly in sink:
```yaml
sink:
  data:
    field: "{{ result.data.command_0.rows[0].value }}"  # Direct reference
```

### JSON/JSONB Column Errors

**Cause**: Python `None` becomes string `'None'` instead of SQL `NULL`.

**Fix**: Remove optional JSONB fields or use SQL NULL:
```yaml
data:
  validation_errors: null  # Don't use Python None
```

## Current Test Coverage

**Version 15** tests the following playbooks:

1. **hello_world** (`tests/fixtures/playbooks/hello_world`)
   - Expected: COMPLETED status, ≥3 events
   - Tests: Basic playbook execution

2. **test_start_with_action** (`tests/control-flow/start_with_action`)
   - Expected: COMPLETED status, ≥2 events
   - Tests: Workflows that start with actions

3. **test_vars_simple** (`test/vars_simple`)
   - Expected: COMPLETED status, ≥2 events
   - Tests: Variable handling

## Architecture Details

### NoETL Async Execution Flow

```
1. Master test playbook starts
   ↓
2. Step: test_playbook (tool: playbook)
   - Server enqueues nested playbook
   - Returns immediately with execution_id
   - Status: "running" (not final status!)
   ↓
3. Step: wait_for_completion (tool: python)
   - Sleeps for N seconds
   - Allows nested playbook time to execute
   ↓
4. Nested playbook executes in background
   - Worker picks up job
   - Executes steps
   - Reports events to server
   - Completes asynchronously
   ↓
5. Step: validate_results (tool: postgres)
   - Queries noetl.event table
   - Gets final_status from last event
   - Counts total events
   - Computes test_passed boolean
   ↓
6. Sink: Save to regression_results
   - Inserts validation results
   - Uses postgres plugin's command_0.rows structure
```

### Why This Pattern?

**❌ What doesn't work:**
- `return_step` parameter - doesn't wait for completion
- Accessing `{{ test_playbook.status }}` - only has initial "running" status
- Using `vars:` block - extractions may not propagate
- Workbook tasks with Python postgres queries - psycopg2 not installed

**✅ What works:**
- Explicit wait step with `asyncio.sleep()`
- Postgres queries against `noetl.event` table
- Direct result access: `result.data.command_0.rows[0].*`
- Sink after validation step

### Event Log Structure

The `noetl.event` table contains all execution events:

```sql
SELECT 
  event_id,
  event_type,
  node_name,
  status,
  error,
  created_at
FROM noetl.event
WHERE execution_id = <nested_execution_id>
ORDER BY event_id;

-- Typical events for successful playbook:
-- playbook_started   | STARTED
-- workflow_started   | STARTED  
-- step_started       | RUNNING
-- action_started     | RUNNING
-- action_completed   | COMPLETED
-- step_completed     | COMPLETED
-- workflow_completed | COMPLETED
-- playbook_completed | COMPLETED
```

The last event's `status` field determines if the playbook succeeded.

## Future Enhancements

1. **Expand Coverage**: Add remaining 53 playbooks from `tests/fixtures/playbooks/`
2. **Parallel Execution**: Use `next: []` array to run multiple tests concurrently
3. **Expected Results**: Populate `noetl_test.expected_results` for baseline comparisons
4. **Performance Metrics**: Track execution time trends
5. **Failure Alerts**: Integrate with notification systems
6. **CI/CD Integration**: Auto-run on code changes

## Files

- `create_test_schema.yaml` - Database schema setup
- `master_regression_test.yaml` - Main orchestrator (Version 15)
- `README.md` - This documentation

## Related Documentation

- [NoETL Playbook DSL](../../../docs/dsl_spec.md)
- [Event-Driven Architecture](../../../docs/playbook_execution_flow.md)
- [Postgres Plugin](../../../docs/database_refactoring_summary.md)
- [Task Automation](../../../ci/taskfile/test.yml)

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
