# NoETL Regression Testing Framework

Self-testing framework using NoETL's native playbook composition to validate all test playbooks and prevent regressions.

## Architecture & Design

### Core Concept

NoETL's **event-driven, asynchronous architecture** requires a specific testing approach:
- Each step executes in isolation on a worker
- Server coordinates via events (command → event → command → event)
- `tool: playbook` triggers a child execution and waits for completion
- Sub-playbook executes and parent step returns when child completes
- Validation queries the event log after completion

### Workflow Pattern

```yaml
# 1. Execute test playbook (waits for completion)
- step: test_playbook
  tool:
    kind: playbook
    path: catalog/path/to/playbook
  next:
    - step: wait_for_completion

# 2. Wait for event persistence
- step: wait_for_completion
  tool:
    kind: python
    libs:
      asyncio: asyncio
    args: {}
    code: |
      await asyncio.sleep(3)  # Ensure events persisted
      result = {"status": "success", "data": {"waited": True}}
  next:
    - step: validate_results

# 3. Query postgres for execution results
- step: validate_results
  tool:
    kind: postgres
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
    tool:
      kind: postgres
      table: noetl_test.regression_results
    data:
      test_run_id: "{{ workload.test_run_id }}"
      playbook_name: "{{ result.data.command_0.rows[0].test_name }}"
      status: "{{ result.data.command_0.rows[0].final_status }}"
      test_passed: "{{ result.data.command_0.rows[0].test_passed }}"
```

### Key Design Principles

1. **Parent Waits for Child**: `tool: playbook` waits for sub-playbook completion
2. **Wait Step**: Required buffer for all events to be persisted to database
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
noetl run tests/fixtures/playbooks/regression_test/create_test_schema.yaml
```

Creates `noetl_test` schema with:
- `regression_results` - Individual test results
- `regression_summary` - Test run summaries
- `expected_results` - Baseline expectations

### 2. Run regression tests

```bash
noetl run tests/fixtures/playbooks/regression_test/regression_test.yaml
```

Executes `master_regression_test.yaml` which:
- Tests playbooks: hello_world, test_start_with_action, test_vars_simple
- Validates execution status and step counts
- Saves results to database
- Generates summary report

### 3. View results

Query latest test results from `noetl_test.regression_results`:

```bash
kubectl exec -it -n postgres deploy/postgres -- psql -U noetl -d noetl -c \
  "SELECT test_run_id, playbook_name, test_passed, status, step_count, execution_id
   FROM noetl_test.regression_results ORDER BY test_timestamp DESC LIMIT 20"
```

## Usage Examples

### Running Tests

**Via NoETL CLI:**
```bash
# Run regression tests
noetl run tests/fixtures/playbooks/regression_test/regression_test.yaml

# Register master test playbook
noetl register tests/fixtures/playbooks/regression_test/master_regression_test.yaml \
  --host localhost --port 8082

# Execute test suite
noetl run catalog/tests/fixtures/playbooks/regression_test/master_regression_test \
  -r distributed \
  --host localhost --port 8082 \
  --set pg_auth=pg_k8s
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
kubectl exec -n postgres deploy/postgres -- psql -U demo -d demo_noetl -c \
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
  tool:
    kind: playbook
    path: tests/fixtures/playbooks/my_category/my_playbook
  next:
    - step: wait_for_my_playbook

- step: wait_for_my_playbook
  desc: "Wait for my_playbook to complete"
  tool:
    kind: python
    libs:
      asyncio: asyncio
    args: {}
    code: |
      await asyncio.sleep(3)  # Adjust wait time as needed
      result = {"status": "success", "data": {"waited": True}}
  next:
    - step: validate_my_playbook

- step: validate_my_playbook
  desc: "Validate my_playbook results"
  tool:
    kind: postgres
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
    tool:
      kind: postgres
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

The `asyncio.sleep(3)` provides a buffer for event persistence:
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

**Cause**: Validation step queried events before all events were persisted.

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

Tests the following playbooks:

1. **hello_world** (`tests/fixtures/playbooks/hello_world`)
   - Expected: COMPLETED status, >=3 events
   - Tests: Basic playbook execution

2. **test_start_with_action** (`tests/control-flow/start_with_action`)
   - Expected: COMPLETED status, >=2 events
   - Tests: Workflows that start with actions

3. **test_vars_simple** (`test/vars_simple`)
   - Expected: COMPLETED status, >=2 events
   - Tests: Variable handling

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
          noetl run automation/infrastructure/kind.yaml --set action=create
          noetl run automation/infrastructure/postgres.yaml --set action=deploy
          noetl run automation/deployment/noetl-stack.yaml --set action=deploy

      - name: Run regression tests
        run: noetl run tests/fixtures/playbooks/regression_test/regression_test.yaml

      - name: Check results
        run: |
          # Query test results and fail if any tests failed
          SUCCESS_RATE=$(kubectl exec -n postgres deploy/postgres -- psql -U noetl -d noetl -t -c \
            "SELECT success_rate FROM noetl_test.regression_summary ORDER BY test_timestamp DESC LIMIT 1")
          if [ "$SUCCESS_RATE" != "100.00" ]; then
            echo "Tests failed! Success rate: $SUCCESS_RATE"
            exit 1
          fi
```

## Development Workflow

### Daily Development

```bash
# 1. Make code changes
vim noetl/tools/tools/duckdb/config.py

# 2. Build and deploy
noetl build
noetl k8s deploy

# 3. Run regression tests
noetl run tests/fixtures/playbooks/regression_test/regression_test.yaml

# 4. Check results
kubectl exec -it -n postgres deploy/postgres -- psql -U noetl -d noetl -c \
  "SELECT playbook_name, test_passed, status FROM noetl_test.regression_results ORDER BY test_timestamp DESC LIMIT 10"

# 5. If failures, investigate
# View execution details in NoETL
# Check worker/server logs
kubectl logs -n noetl deployment/noetl-server -f
kubectl logs -n noetl deployment/noetl-worker -f
```

### Before Committing

```bash
# Run full regression test
noetl run tests/fixtures/playbooks/regression_test/regression_test.yaml

# Verify all tests passed
kubectl exec -it -n postgres deploy/postgres -- psql -U noetl -d noetl -c \
  "SELECT success_rate FROM noetl_test.regression_summary ORDER BY test_timestamp DESC LIMIT 1"
# Should show 100.00%
```

## Files

- `create_test_schema.yaml` - Database schema setup
- `master_regression_test.yaml` - Main orchestrator
- `README.md` - This documentation

## Related Documentation

- [NoETL Playbook DSL](/docs/reference/dsl/spec)
- [Event-Driven Architecture](/docs/reference/architecture_design)
- [Postgres Plugin](/docs/reference/tools/postgres)

## Future Enhancements

1. **Expand Coverage**: Add remaining playbooks from `tests/fixtures/playbooks/`
2. **Parallel Execution**: Use iterator with async mode
3. **Expected Results Baseline**: Populate `noetl_test.expected_results` for baseline comparisons
4. **Performance Metrics**: Track execution time trends
5. **Failure Alerts**: Integrate with notification systems
6. **Dashboard**: Grafana visualization of test trends
