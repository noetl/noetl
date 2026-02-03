# Regression Test Performance Optimization

## Problem

The original `master_regression_test.yaml` runs **52 playbooks sequentially** using event-driven flow control (`case` + `when` + `then` + `next`). Each playbook waits for the previous one to complete before starting, resulting in:

- **Total execution time**: 1-2 minutes for the full suite
- **Individual playbook overhead**: 4-36 seconds per playbook
- **Cumulative delay**: Sum of all individual execution times

Example from execution log:
```
Execution ID: 554376338463785455
Playbook: tests/fixtures/playbooks/regression_test/master_regression_test
Status: RUNNING
Duration: 1m 21s
```

## Root Cause

Sequential execution with event-driven routing:
```yaml
- step: test1
  tool:
    kind: playbook
    path: test1
  case:
    - when: "{{ event.name == 'call.done' }}"
      then:
        - next:
            - step: test2

- step: test2
  tool:
    kind: playbook
    path: test2
  case:
    - when: "{{ event.name == 'call.done' }}"
      then:
        - next:
            - step: test3
```

This pattern creates a **dependency chain** where test2 can't start until test1 completes, test3 can't start until test2 completes, etc.

## Solution: Parallel Execution with Iterator

The optimized `master_regression_test_parallel.yaml` uses NoETL's **iterator with async mode** to run playbooks concurrently:

```yaml
- step: run_tests_parallel
  desc: "Run all test playbooks in parallel"
  tool:
    kind: playbook
    path: "{{ test_playbook }}"
    retry:
      max_attempts: 2
      retry_on: ["timeout"]
  loop:
    in: "{{ workload.test_playbooks }}"
    iterator: test_playbook
    mode: async              # Parallel execution
    concurrency: 10          # Limit concurrent executions
  next:
    - step: generate_summary
```

### Key Configuration

| Parameter | Value | Impact |
|-----------|-------|--------|
| `mode: async` | Parallel execution | All playbooks run concurrently (up to concurrency limit) |
| `concurrency: 10` | Max 10 concurrent | Prevents overwhelming the worker pool |
| `loop.in` | Array of playbook paths | Single declaration of all tests |
| `iterator` | Variable name | Each iteration gets the playbook path |

## Performance Improvement

### Before (Sequential)
- **Execution time**: 1m 21s (81 seconds)
- **Pattern**: N playbooks × avg 1.5s each = 81s total
- **Parallelism**: 1 (single playbook at a time)

### After (Parallel)
- **Expected execution time**: 15-25 seconds
- **Pattern**: max(playbook_duration) with concurrency limit
- **Parallelism**: 10 concurrent playbooks
- **Speedup**: 3-5x faster

### Calculation
```
Sequential: 48 playbooks × ~1.7s avg = 81s
Parallel: max(playbook_durations) with batching
  - Longest playbook: ~17s (save_all_storage_types)
  - Batches: 48 playbooks / 10 concurrency = 5 batches
  - Estimated: 5 batches × 3-5s avg = 15-25s total
```

## Implementation Details

### Setup Phase (Sequential)
Some playbooks **must** run sequentially because they create database objects:

```yaml
- step: setup_schema
  desc: "Run setup playbooks sequentially (create schema and tables)"
  tool:
    kind: playbook
    path: "{{ playbook_path }}"
    payload:
      pg_auth: "{{ workload.pg_auth }}"
  loop:
    in: "{{ workload.setup_playbooks }}"
    iterator: playbook_path
    mode: sequential          # Sequential to avoid race conditions
```

Setup playbooks:
- `tests/fixtures/playbooks/regression_test/create_test_schema`
- `tests/fixtures/playbooks/save_storage_test/create_tables`

### Test Phase (Parallel)
All test playbooks run concurrently:

```yaml
workload:
  test_playbooks:
    - tests/fixtures/playbooks/hello_world
    - tests/control-flow/start_with_action
    - tests/pagination/basic/basic
    # ... 45 more playbooks
```

### Summary Phase (Sequential)
After all tests complete, generate summary:

```yaml
- step: generate_summary
  desc: "Generate regression test summary"
  tool:
    kind: postgres
    auth: "{{ workload.pg_auth }}"
    command: |
      -- Count child executions by status
      WITH child_executions AS (...)
      INSERT INTO noetl_test.regression_summary (...)
```

## Usage

### Run Parallel Regression Test
```bash
noetl run tests/fixtures/playbooks/regression_test/master_regression_test_parallel
```

### Compare Performance
```bash
# Sequential (original)
time noetl run tests/fixtures/playbooks/regression_test/master_regression_test

# Parallel (optimized)
time noetl run tests/fixtures/playbooks/regression_test/master_regression_test_parallel
```

## Best Practices

### When to Use Parallel Execution

✅ **Use parallel execution when**:
- Tests are independent (no shared state)
- No database schema conflicts (tables already exist)
- Worker pool can handle concurrency (10+ workers available)
- Faster feedback is important (CI/CD pipelines)

❌ **Avoid parallel execution when**:
- Tests create database objects (use sequential for DDL)
- Tests modify shared global state
- External APIs have rate limits
- Debugging is needed (sequential easier to trace)

### Concurrency Tuning

| Worker Pool Size | Recommended Concurrency | Rationale |
|------------------|-------------------------|-----------|
| 1-2 workers | `concurrency: 2` | Avoid queue saturation |
| 3-5 workers | `concurrency: 5` | Balance throughput and resource usage |
| 6-10 workers | `concurrency: 10` | Maximize parallelism |
| 10+ workers | `concurrency: 15-20` | High-throughput scenarios |

Check worker pool size:
```bash
kubectl get pods -n noetl -l app=noetl-worker
```

### Retry Strategy

Both sequential and parallel tests use retry configuration:
```yaml
retry:
  max_attempts: 2
  retry_on: ["timeout"]
```

This handles transient failures without manual intervention.

## Monitoring Parallel Execution

### Check Execution Progress
```bash
# Get execution ID from noetl run output
noetl status <execution_id>
```

### Query Database for Results
```sql
-- Count completed child executions
SELECT
  COUNT(*) FILTER (WHERE final_status = 'COMPLETED') as completed,
  COUNT(*) FILTER (WHERE final_status = 'FAILED') as failed,
  COUNT(*) FILTER (WHERE final_status = 'RUNNING') as running
FROM (
  SELECT
    CASE
      WHEN EXISTS (
        SELECT 1 FROM noetl.event e2
        WHERE e2.execution_id = e.execution_id
        AND e2.event_type = 'playbook_completed'
      ) THEN 'COMPLETED'
      WHEN EXISTS (
        SELECT 1 FROM noetl.event e2
        WHERE e2.execution_id = e.execution_id
        AND e2.event_type = 'playbook_failed'
      ) THEN 'FAILED'
      ELSE 'RUNNING'
    END as final_status
  FROM noetl.event e
  WHERE parent_execution_id = <execution_id>
  AND event_type = 'playbook_started'
) child_executions;
```

### Check Regression Summary
```sql
SELECT * FROM noetl_test.regression_summary
WHERE test_run_id = <execution_id>;
```

## Troubleshooting

### Issue: "Worker pool saturated"
**Symptom**: Tests timeout or queue for long time
**Solution**: Reduce `concurrency` value:
```yaml
loop:
  mode: async
  concurrency: 5  # Reduce from 10
```

### Issue: "Database connection pool exhausted"
**Symptom**: `psycopg2.OperationalError: FATAL: too many connections`
**Solution**: 
1. Increase PostgreSQL `max_connections`
2. Reduce test concurrency
3. Add connection pooling (PgBouncer)

### Issue: "Test results incomplete"
**Symptom**: Summary shows fewer tests than expected
**Solution**: Check for failed setup phase:
```sql
SELECT * FROM noetl.event
WHERE execution_id = <execution_id>
AND event_type = 'playbook_failed'
AND node_name LIKE 'setup%';
```

## Future Enhancements

### Grouped Parallel Execution
Run tests in logical groups with different concurrency levels:

```yaml
# Fast tests: high concurrency
- step: run_fast_tests
  loop:
    in: "{{ workload.fast_tests }}"
    mode: async
    concurrency: 20

# Slow tests: lower concurrency
- step: run_slow_tests
  loop:
    in: "{{ workload.slow_tests }}"
    mode: async
    concurrency: 5
```

### Dynamic Concurrency
Adjust concurrency based on available workers:

```yaml
workload:
  concurrency: "{{ (worker_count * 0.8) | int }}"  # 80% of workers
```

### Test Sharding
Split tests across multiple regression playbook executions:

```yaml
workload:
  shard_index: 1
  shard_count: 3
  test_playbooks: "{{ all_tests | shard(shard_index, shard_count) }}"
```

## References

- [NoETL Iterator Documentation](../../features/iterator.md)
- [Loop Modes: Sequential vs Async](../../reference/playbook/steps/iterator.md)
- [Performance Best Practices](../../guides/performance.md)
- [Worker Pool Configuration](../../reference/configuration.md#worker-pool)

## Migration Guide

### Converting Sequential to Parallel

1. **Extract playbook list**:
   ```yaml
   workload:
     test_playbooks:
       - test1
       - test2
       - test3
   ```

2. **Replace sequential steps with iterator**:
   ```yaml
   - step: run_tests
     tool:
       kind: playbook
       path: "{{ test }}"
     loop:
       in: "{{ workload.test_playbooks }}"
       iterator: test
       mode: async
       concurrency: 10
   ```

3. **Identify setup dependencies**:
   - Move DDL/schema playbooks to separate sequential loop
   - Run setup before parallel test execution

4. **Test and tune concurrency**:
   - Start with `concurrency: 5`
   - Monitor worker utilization
   - Increase until worker pool saturates or tests timeout
   - Typical sweet spot: 8-12 for medium workloads

5. **Verify results**:
   - Compare test counts (all tests should run)
   - Check summary table for accuracy
   - Validate failed test reporting

### Rollback Plan

If parallel execution causes issues, the original sequential playbook remains available:
```bash
noetl run tests/fixtures/playbooks/regression_test/master_regression_test
```
