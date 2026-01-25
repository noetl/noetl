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

## Test Infrastructure

### Pagination Test Server

NoETL includes a dedicated FastAPI test server for testing HTTP pagination patterns. This server runs within the Kubernetes cluster and provides consistent, predictable pagination endpoints for regression tests.

**Deployment:**
```bash
# Deploy test server
kubectl apply -f ci/manifests/test-server/

# Check status
kubectl get pods -n test-server

# Test endpoints
curl http://localhost:30555/health

# View logs
kubectl logs -n test-server deployment/paginated-api
```

**Access:**
- **ClusterIP**: `paginated-api.test-server.svc.cluster.local:5555` (internal)
- **NodePort**: `http://localhost:30555` (external)

**Endpoints:**
- `GET /health` - Health check
- `GET /api/v1/assessments?page={n}` - Page-number based pagination (35 items, 10 per page)
- `GET /api/v1/users?offset={n}&limit={n}` - Offset-based pagination
- `GET /api/v1/events?cursor={token}` - Cursor-based pagination
- `GET /api/v1/flaky?page={n}` - Simulated failures for retry testing

**Configuration:**
- Source: `tests/fixtures/servers/paginated_api.py`
- Docker: `docker/test-server/Dockerfile`
- Manifests: `ci/manifests/test-server/`

**Port Mapping:**
The test server's NodePort (30555) must be configured in the kind cluster configuration (`ci/kind/config.yaml`). If you recreate the cluster, the port mapping is automatically included.

## Architecture

### Event-Driven Design

NoETL's asynchronous, event-driven architecture requires specific testing patterns:

1. **Each step executes in isolation** - Workers pull jobs independently
2. **Server coordinates via events** - Command → event → command flow
3. **`tool: playbook` triggers new execution chain** - Creates child execution_id with parent_execution_id reference
4. **Both executions run in parallel** - Parent and child execution chains proceed independently
5. **Parent step waits for child completion** - Server analyzes events from child execution to determine when complete
6. **Validation still needs wait time** - Child execution takes time to complete all its steps
7. **Event log contains final status** - Query `noetl.event` table for child execution completion

### Three-Step Pattern

**How `tool: playbook` Works:**
1. **Triggers new execution chain** - Creates child execution with new execution_id
2. **Sets parent reference** - Child execution has `parent_execution_id` pointing to parent
3. **Server monitors child events** - Analyzes events from workers to determine child completion
4. **Parent step completes when child completes** - Step waits for child execution to finish
5. **Both run via worker events** - Parent and child executions coordinated through event stream

**Why We Still Need Wait Step:**
- Parent step does wait for child completion before proceeding to `next:`
- BUT the validation step needs the child execution_id to query its events
- The wait step ensures child execution has fully completed and all events are persisted
- Without wait, we might query events while they're still being written

```yaml
# 1. Execute test playbook (triggers child execution chain)
- step: test_playbook
  tool:
    kind: playbook
    path: tests/fixtures/playbooks/hello_world
  next:
    - step: wait_for_completion
  # Parent step waits for child execution to complete
  # Returns with child execution_id once child finishes

# 2. Wait for event persistence and processing
- step: wait_for_completion
  tool:
    kind: python
    libs:
      asyncio: asyncio
    args: {}
    code: |
      # Pure Python code - no imports, no def main()
      await asyncio.sleep(3)  # Ensure events persisted
      result = {"status": "success", "data": {"waited": True}}
  next:
    - step: validate_results
  # Gives time for all child events to be written to DB

# 3. Query events and validate
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
      test_passed: "{{ result.data.command_0.rows[0].test_passed }}"
```

### Why the Wait Step is Necessary

**How `tool: playbook` Execution Works:**
1. Parent step makes HTTP POST to `/api/run/playbook`
2. Server creates new execution chain with child execution_id
3. Child execution_id references parent via `parent_execution_id`
4. **Parent step WAITS for child execution to complete** (via event analysis)
5. Server monitors child execution events from workers
6. When child execution completes, parent step returns child execution_id
7. Parent step then proceeds to `next:`

**Why We Still Need Wait Step:**
- Parent step does wait for child completion internally
- However, this is done via event stream analysis
- Events are processed asynchronously by workers
- Small timing gap between step completion and all events being persisted
- Validation queries need events to be fully written to database

**Timeline Analysis (execution 508709863430554191):**
```
21:15:42.378589 - Child execution starts (new execution_id created)
21:15:42.417788 - Parent step sees child completion event
21:15:42.422100 - Validation step starts (4ms later - too fast!)
21:15:42.538732 - All child events persisted (160ms total)
→ Validation queried 116ms before all events were written
```

**With wait step:**
```
Step 1: tool: playbook → waits for child execution → returns child execution_id
Step 2: Sleep 3 seconds → ensures all child events persisted to DB
Step 3: Query events → all child execution events available
```

## Quick Start

### Setup Test Schema

Create the test database schema:

```bash
noetl run tests/fixtures/playbooks/regression_test/create_test_schema.yaml
```

This creates:
- `noetl_test.regression_results` - Individual test results
- `noetl_test.regression_summary` - Test run summaries
- `noetl_test.expected_results` - Baseline expectations

### Run Tests

Execute the regression test suite:

```bash
# Run regression tests
noetl run tests/fixtures/playbooks/regression_test/regression_test.yaml

# View latest results via SQL
kubectl exec -it -n postgres deploy/postgres -- psql -U noetl -d noetl -c \
  "SELECT playbook_name, test_passed, status FROM noetl_test.regression_results ORDER BY test_timestamp DESC LIMIT 20"
```

### Via CLI

```bash
# Register master test playbook
noetl register tests/fixtures/playbooks/regression_test/master_regression_test.yaml \
  --host localhost --port 8082

# Execute test suite (distributed mode)
noetl run catalog/tests/fixtures/playbooks/regression_test/master_regression_test \
  -r distributed \
  --host localhost --port 8082 \
  --set pg_auth=pg_k8s
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

Add a new test to `master_regression_test.yaml`. The wait step ensures all child execution events are persisted:

```yaml
# 1. Execute test playbook (creates child execution chain)
- step: test_my_playbook
  desc: "Test my_playbook"
  tool:
    kind: playbook
    path: tests/fixtures/playbooks/my_category/my_playbook
  next:
    - step: wait_for_my_playbook
  # This step:
  # - Triggers child execution with new execution_id
  # - Waits for child completion via event analysis
  # - Returns child execution_id when complete
  # - Then proceeds to next step

# 2. Wait for event persistence (REQUIRED)
- step: wait_for_my_playbook
  desc: "Ensure all child execution events are persisted"
  tool:
    kind: python
    libs:
      asyncio: asyncio
    args: {}
    code: |
      # Pure Python code - no imports, no def main()
      await asyncio.sleep(3)  # Adjust based on playbook complexity
      result = {"status": "success", "data": {"waited": True}}
  next:
    - step: validate_my_playbook
  # Child execution completed, but events may still be
  # writing to database. This ensures full persistence.

# 3. Validate and save (all child events now in database)
- step: validate_my_playbook
  desc: "Query child execution events for validation"
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

**Cause**: Event persistence lag - validation queried before all events written to database

**Explanation**:
- `tool: playbook` triggers child execution with new execution_id
- Parent step waits for child completion via event stream analysis
- When child completes, parent step returns child execution_id
- However, workers may still be writing final events to database
- If wait time too short, validation queries incomplete event set

**Solution**: Increase wait time:
```yaml
await asyncio.sleep(5)  # Increase from 3 to 5 seconds for complex playbooks
```

**Diagnosis**: Check parent/child execution relationship:
```sql
-- Find parent and child executions
SELECT
  e1.execution_id as parent_exec_id,
  e2.execution_id as child_exec_id,
  e2.event_type,
  e2.created_at
FROM noetl.event e1
JOIN noetl.event e2 ON e2.parent_execution_id = e1.execution_id
WHERE e1.execution_id = <parent_id>
ORDER BY e2.created_at;
```

### Missing Wait Step

**Symptom**: Test validation gets incomplete event data

**Cause**: No buffer time for event persistence after child execution completes

**Solution**: Always add wait step between execute and validate:
```yaml
- step: test_playbook
  tool:
    kind: playbook
    path: catalog/path
  next: [step: wait_step]  # Required for event persistence

- step: wait_step
  tool:
    kind: python
    libs:
      asyncio: asyncio
    args: {}
    code: |
      # Pure Python code - no imports, no def main()
      await asyncio.sleep(3)  # Buffer for event writes
      result = {"status": "success", "data": {"waited": True}}
  next: [step: validate]
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
  tool:
    kind: postgres
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
  tool:
    kind: python
    libs:
      os: os
    args: {}
    code: |
      # Pure Python code - no imports, no def main()
      result = {
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
          noetl run automation/infrastructure/kind.yaml --set action=create
          noetl run automation/infrastructure/postgres.yaml --set action=deploy
          noetl run automation/deployment/noetl-stack.yaml --set action=deploy

      - name: Run regression tests
        run: noetl run tests/fixtures/playbooks/regression_test/regression_test.yaml

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

## See Also

- [DSL Specification](/docs/reference/dsl/spec)
- [Playbook Structure](/docs/features/playbook_structure)
- [PostgreSQL Tool](/docs/reference/tools/postgres)
- [Local Development Setup](/docs/development/local_dev_setup)
