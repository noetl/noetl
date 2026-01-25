# NoETL Playbook Regression Testing Framework

Complete test suite for validating all 56 playbooks to prevent regressions when adding new features.

## Overview

This framework provides:
- **Automated playbook execution** - All playbooks tested systematically
- **Expected result validation** - Compare actual vs expected outputs
- **Baseline creation** - Capture current behavior as expected baseline
- **Category filtering** - Test specific groups of playbooks
- **Single playbook testing** - Debug individual playbooks
- **Regression detection** - Catch when changes break existing functionality

## Quick Start

### 1. Ensure K8s cluster is running

```bash
# Check cluster health
kubectl get pods -A

# If not running, bring up the cluster
noetl run automation/setup/bootstrap.yaml
```

### 2. Register test credentials

```bash
noetl run tests/fixtures/playbooks/regression_test/register_credentials.yaml
```

### 3. Run regression tests

```bash
# Run all tests
noetl run tests/fixtures/playbooks/regression_test/regression_test.yaml

# Run specific playbook test
noetl run tests/fixtures/playbooks/hello_world/hello_world.yaml
```

## Running Tests

### Using NoETL CLI

```bash
# Complete regression test suite (all playbooks)
noetl run tests/fixtures/playbooks/regression_test/regression_test.yaml

# Test specific playbook
noetl run tests/fixtures/playbooks/hello_world/hello_world.yaml

# List all playbooks
ls tests/fixtures/playbooks/
```

### Using pytest

```bash
# Run all tests with verbose output
pytest tests/test_playbook_regression.py -v

# Run specific playbook
pytest tests/test_playbook_regression.py -v -k "hello_world"

# Run category
pytest tests/test_playbook_regression.py -v --category=basic

# Update expected results
pytest tests/test_playbook_regression.py -v --update-expected

# Show full traceback on failure
pytest tests/test_playbook_regression.py -v --tb=long

# Stop on first failure
pytest tests/test_playbook_regression.py -v -x
```

## Test Workflow

### First Time Setup (Creating Baselines)

When setting up regression testing for the first time:

```bash
# 1. Ensure cluster is healthy
kubectl get nodes
kubectl get pods -A

# 2. Register credentials
noetl run tests/fixtures/playbooks/regression_test/register_credentials.yaml

# 3. Run regression tests to create baselines
noetl run tests/fixtures/playbooks/regression_test/regression_test.yaml
```

### Regular Development Workflow

After making code changes:

```bash
# 1. Run regression tests
noetl run tests/fixtures/playbooks/regression_test/regression_test.yaml

# 2. If tests fail, investigate
pytest tests/test_playbook_regression.py -v -k "failed_playbook_name"

# 3. View logs
kubectl logs -n noetl deployment/noetl-server -f
kubectl logs -n noetl deployment/noetl-worker -f

# 4. Run full regression suite before committing
noetl run tests/fixtures/playbooks/regression_test/regression_test.yaml
```

## Test Configuration

### Configuration File: `tests/fixtures/playbook_test_config.yaml`

Defines all playbooks and their test parameters:

```yaml
playbooks:
  - name: hello_world
    path: tests/fixtures/playbooks/hello_world/hello_world
    category: basic
    enabled: true
    requires_credentials: []
    expected_result_file: hello_world.json
    validation:
      execution_status: completed
      min_steps: 3
      required_steps:
        - start
        - test_step
        - end
```

### Key Fields

- **name**: Unique playbook identifier
- **path**: Playbook catalog path
- **category**: Group for filtering (basic, data_transfer, etc.)
- **enabled**: Whether to include in test runs
- **requires_credentials**: List of credentials needed (pg_k8s, gcs_hmac_local, etc.)
- **requires_setup**: Setup tasks to run first (e.g., create_tables)
- **expected_result_file**: JSON file with expected output
- **validation**: Validation rules for execution

### Validation Rules

```yaml
validation:
  execution_status: completed  # or failed for negative tests
  min_steps: 5                 # Minimum steps that must execute
  required_steps:              # Steps that must be present
    - start
    - fetch_data
    - end
  expect_error: true           # For negative tests
  error_pattern: "tool.*required"  # Regex for error validation
```

## Test Categories

- **basic**: Core functionality (hello_world, vars, cache)
- **data_transfer**: Data movement between systems
- **control_flow**: Conditional logic and branching
- **storage**: Save/sink operations
- **api_integration**: External API calls, pagination
- **advanced**: Retry logic, composition, script execution
- **negative_test**: Expected failures for validation

## Expected Results

### Directory Structure

```
tests/fixtures/expected_results/
├── hello_world.json
├── save_edge_cases.json
├── control_flow_workbook.json
└── ...
```

### Expected Result Format

```json
{
  "execution_id": 123456789,
  "status": "completed",
  "events": [
    {
      "event_type": "execution_started",
      "step_name": "start",
      ...
    },
    {
      "event_type": "action_completed",
      "step_name": "test_step",
      ...
    }
  ],
  "final_status": {
    "status": "completed",
    "execution_id": 123456789,
    ...
  }
}
```

### Normalization

Dynamic fields are normalized (removed) before comparison:
- `execution_id`
- `timestamp`
- `created_at`
- `updated_at`

This ensures tests compare logical behavior, not runtime-specific values.

## Debugging Failed Tests

### Step 1: Run with verbose output

```bash
pytest tests/test_playbook_regression.py -v -k "failed_playbook" --tb=long
```

### Step 2: Check execution events

```bash
# Query NoETL API for execution details
curl http://localhost:8082/api/execution/<execution_id>/events | jq .
```

### Step 3: Check logs

```bash
# Worker logs
kubectl logs -n noetl deployment/noetl-worker -f

# Server logs
kubectl logs -n noetl deployment/noetl-server -f
```

### Step 4: Manual execution

```bash
# Execute playbook manually
noetl run tests/fixtures/playbooks/path/to/playbook.yaml
```

## Best Practices

### Before Committing Changes

1. **Run regression tests**
   ```bash
   noetl run tests/fixtures/playbooks/regression_test/regression_test.yaml
   ```

2. **Check logs for errors**
   ```bash
   kubectl logs -n noetl deployment/noetl-server | grep ERROR
   ```

### When Adding Features

1. **Test existing playbooks first**
   - Ensure current tests pass before changes

2. **Make code changes**

3. **Run regression tests**
   - Identify what broke

4. **Fix or update baselines**
   - Fix bugs OR update expected results if behavior change is correct

5. **Add new test cases**
   - Create new playbooks for new features
   - Add to test configuration
   - Create baseline

### Continuous Integration

Add to CI/CD pipeline:

```yaml
# .github/workflows/test.yml
- name: Setup cluster
  run: |
    noetl run automation/infrastructure/kind.yaml --set action=create
    noetl run automation/infrastructure/postgres.yaml --set action=deploy
    noetl run automation/deployment/noetl-stack.yaml --set action=deploy

- name: Run regression tests
  run: noetl run tests/fixtures/playbooks/regression_test/regression_test.yaml
```

## Architecture

### Components

1. **PlaybookTestConfig** - Loads test configuration from YAML
2. **NoETLClient** - Async API client for NoETL server
3. **PlaybookValidator** - Validates execution results against expected
4. **pytest fixtures** - Setup environment, client, credentials
5. **pytest parametrize** - Generate test cases from configuration

### Test Flow

```
Load config → Setup environment → For each playbook:
  Register → Execute → Wait completion → Get events → Validate → Compare
```

### Validation Layers

1. **Execution status** - completed/failed
2. **Step count** - Minimum steps executed
3. **Required steps** - Specific steps present
4. **Error patterns** - Expected errors (negative tests)
5. **Result comparison** - Match expected output

## Troubleshooting

### Server not available

```bash
# Check cluster health
kubectl get pods -A

# Restart if needed
noetl run automation/setup/bootstrap.yaml
```

### Credentials not registered

```bash
noetl run tests/fixtures/playbooks/regression_test/register_credentials.yaml
```

### Timeout errors

Increase timeout in `playbook_test_config.yaml`:

```yaml
playbooks:
  - name: slow_playbook
    timeout: 600  # 10 minutes
```

### Test passes locally but fails in CI

- Check environment variables (NOETL_HOST, NOETL_PORT)
- Ensure credentials available in CI environment
- Check timezone configuration (must be UTC)

## Environment Variables

```bash
# NoETL server connection
export NOETL_HOST=localhost
export NOETL_PORT=8082

# For local development
export NOETL_HOST=localhost
export NOETL_PORT=8083
```

## Files

- `tests/test_playbook_regression.py` - Main test framework
- `tests/fixtures/playbook_test_config.yaml` - Test configuration
- `tests/fixtures/expected_results/` - Expected result JSON files
- `tests/fixtures/playbooks/regression_test/` - Regression test playbooks

## Future Enhancements

Potential improvements:

- **Parallel execution** - Run multiple playbooks simultaneously
- **Performance metrics** - Track execution times
- **Coverage reporting** - Which code paths are tested
- **Visual diff tool** - Compare expected vs actual results
- **CI integration** - Automatic baseline updates on merge
- **Flaky test detection** - Identify non-deterministic tests
- **Test data generation** - Auto-generate test payloads
