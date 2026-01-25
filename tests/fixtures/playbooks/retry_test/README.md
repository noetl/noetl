# Retry Test Playbooks

This directory contains test playbooks demonstrating retry functionality for different task types.

## Overview

NoETL supports configurable retry logic for all task types. The retry mechanism is implemented at the execution orchestration level (`noetl/tools/tool/execution.py`) and wraps individual plugin executors, making it task-type agnostic.

## Retry Configuration

Retry can be configured in three ways:

### 1. Simple Boolean
```yaml
retry: true  # Use default retry policy
```

### 2. Integer (Max Attempts)
```yaml
retry: 5  # Retry up to 5 times with defaults
```

### 3. Full Configuration
```yaml
retry:
  max_attempts: 3           # Maximum number of attempts
  initial_delay: 1.0        # Initial delay in seconds
  backoff_multiplier: 2.0   # Exponential backoff multiplier
  max_delay: 60.0           # Maximum delay between retries
  jitter: true              # Add random jitter to delays
  retry_when: "{{ condition }}"  # Jinja2 expression for retry condition
  stop_when: "{{ condition }}"   # Jinja2 expression to stop retrying
```

## Retry Conditions

Retry conditions are Jinja2 expressions with access to:
- `result`: Complete task result
- `status_code`: HTTP status code (for HTTP tasks)
- `error`: Error message if task failed
- `success`: Boolean success flag
- `data`: Task result data
- `attempt`: Current attempt number

## Test Playbooks

### 1. HTTP Retry on Status Code
**File**: `http_retry_status_code.yaml`
- Tests retry based on HTTP status codes
- Retries on 5xx server errors
- Demonstrates exponential backoff

### 2. HTTP Retry with Stop Condition
**File**: `http_retry_with_stop.yaml`
- Tests stop condition that overrides retry
- Stops when receiving 200 status
- Shows retry_when and stop_when interaction

### 3. Python Exception Retry
**File**: `python_retry_exception.yaml`
- Tests retry on Python exceptions
- Simulates random failures
- Demonstrates error-based retry condition

### 4. Postgres Connection Retry
**File**: `postgres_retry_connection.yaml`
- Tests database connection retry
- Retries on connection or query errors
- Uses credential-based authentication

### 5. DuckDB Query Retry
**File**: `duckdb_retry_query.yaml`
- Tests DuckDB query retry
- Retries on query errors
- Simple error detection pattern

### 6. Simple Config Examples
**File**: `retry_simple_config.yaml`
- Demonstrates all three configuration formats
- Shows boolean, integer, and full config
- Single playbook with multiple retry patterns

## Running Tests

Register all retry test playbooks:
```bash
noetl run automation/test/register-retry-tests.yaml
```

Execute specific retry test:
```bash
noetl run tests/fixtures/playbooks/retry_test/http_retry_status_code.yaml
```

## Implementation Details

- Retry logic is in `noetl/tools/tool/retry.py`
- Execution wrapper is in `noetl/tools/tool/execution.py`
- Individual action plugins (http, python, postgres, etc.) are unaware of retry
- Retry evaluation uses Jinja2 template engine for flexible conditions
- Exponential backoff with optional jitter prevents thundering herd

## Best Practices

1. **Set Reasonable Max Attempts**: Start with 3-5 attempts to avoid long delays
2. **Use Specific Conditions**: Target specific errors/status codes instead of retrying everything
3. **Configure Delays Properly**: Balance between quick retry and server load
4. **Add Jitter**: For distributed systems, enable jitter to prevent synchronized retries
5. **Use Stop Conditions**: Define success criteria to stop retrying early
6. **Monitor Attempt Counts**: Check logs to tune retry parameters

## Example Patterns

### Retry on Specific HTTP Status Codes
```yaml
retry_when: "{{ status_code in [500, 502, 503, 504] }}"
```

### Retry on Database Deadlock
```yaml
retry_when: "{{ 'deadlock' in (error|lower) }}"
```

### Retry with Timeout
```yaml
retry_when: "{{ 'timeout' in (error|lower) or status_code == 408 }}"
```

### Stop on Success
```yaml
retry_when: "{{ success == False }}"
stop_when: "{{ success == True }}"
```

### Limit Attempts on Specific Errors
```yaml
retry_when: "{{ attempt <= 2 and 'rate limit' in (error|lower) }}"
```
