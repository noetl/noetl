# Retry Mechanism

NoETL provides a retry mechanism for all task types, allowing tasks to be automatically retried based on configurable conditions.

## Overview

The retry logic is implemented at the execution orchestration level (`noetl/tools/tool/execution.py`), making it available to all action types without requiring individual plugin implementations. This design keeps retry logic abstract and reusable across all task types.

## Architecture

### Implementation Location

- **Retry Module**: `/noetl/tools/tool/retry.py`
  - Contains `RetryPolicy` class for configuration and evaluation
  - Contains `execute_with_retry()` wrapper function

- **Execution Module**: `/noetl/tools/tool/execution.py`
  - Integrates retry wrapper around all plugin executors
  - No changes needed in individual action type plugins

### Design Principles

1. **Task-Type Agnostic**: Retry logic works for all action types (http, python, postgres, duckdb, etc.)
2. **Expression-Based**: Retry conditions use Jinja2 expressions for flexibility
3. **Separation of Concerns**: Individual plugins remain unaware of retry logic
4. **Configurable Backoff**: Supports exponential backoff with jitter to prevent thundering herd

## Configuration

### Simple Boolean
```yaml
retry: true  # Use default retry policy (3 attempts, 1s initial delay)
```

### Integer (Max Attempts Only)
```yaml
retry: 5  # Retry up to 5 times with default settings
```

### Full Configuration
```yaml
retry:
  max_attempts: 3           # Maximum number of execution attempts (default: 3)
  initial_delay: 1.0        # Initial delay in seconds (default: 1.0)
  max_delay: 60.0           # Maximum delay between retries (default: 60.0)
  backoff_multiplier: 2.0   # Exponential backoff multiplier (default: 2.0)
  jitter: true              # Add random jitter to delays (default: true)
  retry_when: "{{ expr }}"  # Jinja2 expression to determine if retry needed
  stop_when: "{{ expr }}"   # Jinja2 expression to stop retrying (overrides retry_when)
```

## Retry Conditions

### Available Variables

Retry condition expressions have access to:

- `result`: Complete task execution result dictionary
- `status_code`: HTTP status code (for HTTP tasks)
- `error`: Error message string if task failed
- `success`: Boolean indicating task success
- `data`: Task result data
- `attempt`: Current attempt number (1-indexed)

### Expression Evaluation

Conditions are Jinja2 templates that must evaluate to a boolean-like value:
- `"true"`, `"1"`, `"yes"` → retry
- Any other value → don't retry

### Example Conditions

#### HTTP Status Codes
```yaml
# Retry on server errors (5xx)
retry_when: "{{ status_code >= 500 and status_code < 600 }}"

# Retry on specific status codes
retry_when: "{{ status_code in [500, 502, 503, 504] }}"

# Retry on any non-success status
retry_when: "{{ status_code != 200 }}"
```

#### Error Messages
```yaml
# Retry on any error
retry_when: "{{ error != None }}"

# Retry on specific error types
retry_when: "{{ 'timeout' in (error|lower) }}"

# Retry on database deadlock
retry_when: "{{ 'deadlock' in (error|lower) }}"
```

#### Success Flag
```yaml
# Retry on failure
retry_when: "{{ success == False }}"

# Stop on success
stop_when: "{{ success == True }}"
```

#### Attempt-Based Logic
```yaml
# Limit retries for specific conditions
retry_when: "{{ attempt <= 2 and 'rate limit' in (error|lower) }}"

# Different conditions based on attempt
retry_when: "{{ (attempt == 1 and status_code >= 500) or (attempt > 1 and status_code == 503) }}"
```

## Backoff Strategy

### Exponential Backoff

Delay calculation: `delay = initial_delay * (backoff_multiplier ^ (attempt - 1))`

Capped at: `min(calculated_delay, max_delay)`

Example with `initial_delay=1.0`, `backoff_multiplier=2.0`:
- Attempt 1: 0s (no delay before first attempt)
- Attempt 2: 1s
- Attempt 3: 2s
- Attempt 4: 4s
- Attempt 5: 8s

### Jitter

When `jitter: true`, adds randomization to prevent synchronized retries:

`actual_delay = calculated_delay * (0.5 + random())`

This creates a delay between 50% and 150% of the calculated delay.

## Usage Examples

### HTTP Retry on Server Errors

```yaml
- step: fetch_data
  tool: http
  method: GET
  url: "{{ api_url }}"
  retry:
    max_attempts: 5
    initial_delay: 2.0
    backoff_multiplier: 2.0
    retry_when: "{{ status_code >= 500 }}"
    stop_when: "{{ status_code == 200 }}"
```

### Python Task with Exception Handling

```yaml
- step: process_data
  tool: python
  code: |
    def main(input_data):
        # Processing logic that might fail
        return result
  retry:
    max_attempts: 3
    initial_delay: 0.5
    retry_when: "{{ error != None }}"
```

### Database Query with Connection Retry

```yaml
- step: query_database
  tool: postgres
  auth:
    type: postgres
    credential: prod_db
  query: "{{ sql_query }}"
  retry:
    max_attempts: 5
    initial_delay: 1.0
    backoff_multiplier: 1.5
    retry_when: "{{ error != None or success == False }}"
```

### DuckDB with Conditional Retry

```yaml
- step: analyze_data
  tool: duckdb
  query: "{{ analysis_query }}"
  retry:
    max_attempts: 3
    initial_delay: 0.5
    retry_when: "{{ 'out of memory' in (error|lower) }}"
```

## Testing

### Test Playbooks

Test playbooks are available in `tests/fixtures/playbooks/retry_test/`:

- `http_retry_status_code.yaml` - HTTP status code retry
- `http_retry_with_stop.yaml` - HTTP with stop condition
- `python_retry_exception.yaml` - Python exception handling
- `postgres_retry_connection.yaml` - Database connection retry
- `duckdb_retry_query.yaml` - DuckDB query retry
- `retry_simple_config.yaml` - All configuration formats

### Running Tests

```bash
# Register and run retry test playbooks
noetl run automation/test/retry-tests.yaml --set action=register
noetl run automation/test/retry-tests.yaml --set action=run-all

# Run specific retry test
noetl run automation/test/retry-tests.yaml --set action=run --set test=http-status
noetl run automation/test/retry-tests.yaml --set action=run --set test=python-exception
```

## Best Practices

### 1. Set Reasonable Max Attempts
Start with 3-5 attempts. Too many attempts can cause long delays.

```yaml
retry:
  max_attempts: 3  # Good starting point
```

### 2. Use Specific Retry Conditions
Target specific errors instead of retrying everything:

```yaml
# Good: Specific condition
retry_when: "{{ status_code in [429, 500, 502, 503] }}"

# Avoid: Too broad
retry_when: "{{ True }}"
```

### 3. Configure Appropriate Delays
Balance between quick retry and avoiding server overload:

```yaml
retry:
  initial_delay: 1.0        # Start with 1 second
  max_delay: 30.0           # Cap at 30 seconds
  backoff_multiplier: 2.0   # Double each time
```

### 4. Enable Jitter for Distributed Systems
Prevent synchronized retries across multiple workers:

```yaml
retry:
  jitter: true  # Add randomization
```

### 5. Use Stop Conditions for Early Exit
Define success criteria to avoid unnecessary retries:

```yaml
retry:
  retry_when: "{{ status_code != 200 }}"
  stop_when: "{{ status_code == 200 }}"  # Exit early on success
```

### 6. Monitor and Tune
Check logs to understand retry patterns and adjust configuration:

```
Task 'fetch_data' will retry after 2.34s (attempt 2/5)
Task 'fetch_data' succeeded on attempt 3
```

## Implementation Notes

### Plugin Integration

No changes required in individual action plugins. The retry wrapper in `execution.py` handles all retry logic:

```python
def execute_task(...):
    return execute_with_retry(
        _execute_task_without_retry,
        task_config,
        task_name,
        context,
        jinja_env,
        task_with,
        log_event_callback
    )
```

### Error Handling

- Exceptions are caught and evaluated against retry conditions
- If retry condition not met, exception is re-raised
- After all attempts exhausted, last exception is raised

### Logging

Retry attempts are logged with details:
- Attempt number and total attempts
- Delay before next retry
- Success/failure status
- Retry condition evaluation results

## Limitations

1. **Async Tasks**: Workbook tasks use async execution which may need special handling
2. **State Management**: Retry logic doesn't persist state across worker restarts
3. **Resource Cleanup**: Tasks should handle their own resource cleanup on failure
4. **Idempotency**: Tasks should be idempotent if retried (especially for data modification)

## Future Enhancements

Potential improvements:

1. **Circuit Breaker**: Stop retrying after consecutive failures
2. **Retry Metrics**: Track retry rates and success patterns
3. **Persistent Retry State**: Store retry attempts in database
4. **Retry Budget**: Limit total retry time across all attempts
5. **Conditional Backoff**: Different backoff strategies based on error type
