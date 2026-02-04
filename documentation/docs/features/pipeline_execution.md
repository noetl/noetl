# Pipeline Execution

Pipeline execution enables atomic, sequential task chains within a single worker, featuring Clojure-style data threading and centralized error handling.

## Overview

The `pipe:` block treats multiple tasks as an atomic unit executed on a single worker. Data flows automatically between tasks via the `_prev` variable (similar to Clojure's `->` threading macro), while `catch.cond` provides centralized error handling with retry, skip, jump, and fail control actions.

## Key Features

| Feature | Description |
|---------|-------------|
| **Data Threading** | `_prev` carries the result of each task to the next |
| **Atomic Execution** | Entire pipeline runs on one worker as a unit |
| **Centralized Error Handling** | `catch.cond` handles all task failures |
| **Control Actions** | retry, skip, jump, fail, continue |
| **Runtime Context** | `_task`, `_prev`, `_err`, `_attempt` available in templates |

## Basic Structure

```yaml
case:
  - when: "{{ event.name == 'step.enter' }}"
    then:
      pipe:
        - task_name_1:
            tool:
              kind: http
              url: "..."

        - task_name_2:
            tool:
              kind: python
              args:
                data: "{{ _prev }}"  # Result from task_name_1
              code: |
                result = transform(data)

        - task_name_3:
            tool:
              kind: postgres
              query: "INSERT INTO ... VALUES ({{ _prev }})"

      catch:
        cond:
          - when: "{{ _task == 'task_name_1' and _err.retryable }}"
            do: retry
            attempts: 5
          - else:
              do: fail

      finally:
        - next:
            - step: continue
```

## Runtime Variables

These variables are available within pipeline execution and can be used in templates:

| Variable | Type | Description |
|----------|------|-------------|
| `_task` | string | Name of the current or failed task |
| `_prev` | any | Result of the last successful task |
| `_err` | object | Structured error info (on failure) |
| `_attempt` | int | Current retry attempt number (1-based) |
| `results` | dict | All task results by name |

### The `_err` Object

When a task fails, `_err` contains:

```yaml
_err:
  kind: "rate_limit"      # Error category
  retryable: true         # Whether retry makes sense
  code: "HTTP_429"        # Tool-specific error code
  message: "Too Many..."  # Human-readable message
  source: "http"          # Tool that produced the error
  http_status: 429        # HTTP status code (if applicable)
  retry_after: 60         # Retry-After header value
  pg_code: "40P01"        # PostgreSQL error code (if applicable)
  exception_type: "KeyError"  # Python exception type
```

### Error Kinds

| Kind | Description | Retryable |
|------|-------------|-----------|
| `connection` | Network connectivity issues | Yes |
| `timeout` | Request/response timeout | Yes |
| `rate_limit` | HTTP 429 Too Many Requests | Yes |
| `server_error` | HTTP 5xx errors | Yes |
| `auth` | HTTP 401/403 | No |
| `not_found` | HTTP 404 | No |
| `client_error` | HTTP 4xx (other) | No |
| `schema` | Data validation error | No |
| `parse` | JSON/XML parsing error | No |
| `db_deadlock` | Database deadlock | Yes |
| `db_connection` | Database connection error | Yes |
| `db_timeout` | Query timeout | Yes |
| `db_constraint` | Unique/FK constraint | No |

## Control Actions

### retry

Retry the failed task or restart from a specific task:

```yaml
catch:
  cond:
    # Retry current task
    - when: "{{ _err.retryable }}"
      do: retry
      attempts: 5
      backoff: exponential  # none, linear, exponential
      delay: 1.0            # Initial delay in seconds

    # Retry from a specific task
    - when: "{{ _task == 'store' and _err.kind == 'db_deadlock' }}"
      do: retry
      from: fetch           # Restart from 'fetch' task
      attempts: 3
```

**Backoff Strategies:**

| Strategy | Formula | Example (delay=1.0) |
|----------|---------|---------------------|
| `none` | 0 | No delay |
| `linear` | delay × attempt | 1s, 2s, 3s, 4s... |
| `exponential` | delay × 2^(attempt-1) | 1s, 2s, 4s, 8s... |

### skip

Skip the failed task and continue to the next:

```yaml
catch:
  cond:
    - when: "{{ _task == 'transform' }}"
      do: skip
      set_prev:             # Optional: set _prev for next task
        items: []
        skipped: true
```

### jump

Jump to a specific task in the pipeline:

```yaml
catch:
  cond:
    - when: "{{ _err.kind == 'not_found' }}"
      do: jump
      to: fallback_task     # Jump to named task
```

### fail

Stop the pipeline immediately:

```yaml
catch:
  cond:
    - when: "{{ _err.kind == 'auth' }}"
      do: fail              # Non-retryable, stop immediately

    - else:
        do: fail            # Default fallback
```

### continue

Continue to the next task despite the error (unusual but allowed):

```yaml
catch:
  cond:
    - when: "{{ _task == 'optional_task' }}"
      do: continue          # Ignore error and proceed
```

## Practical Examples

### Example 1: Pagination with Fetch → Transform → Store

```yaml
- step: process_page
  tool:
    kind: noop
  case:
    - when: "{{ event.name == 'step.enter' }}"
      then:
        pipe:
          - fetch:
              tool:
                kind: http
                url: "{{ api_url }}/data"
                params:
                  page: "{{ vars.current_page }}"

          - transform:
              tool:
                kind: python
                args:
                  data: "{{ _prev }}"
                code: |
                  items = data.get('items', [])
                  result = {
                    'transformed': [process(i) for i in items],
                    'has_more': data.get('has_more', False)
                  }

          - store:
              tool:
                kind: postgres
                credential: my_db
                query: |
                  INSERT INTO results (data, page)
                  VALUES ('{{ _prev.transformed | tojson }}', {{ vars.current_page }})

        catch:
          cond:
            # Retry fetch on transient errors
            - when: "{{ _task == 'fetch' and _err.retryable }}"
              do: retry
              attempts: 5
              backoff: exponential
              delay: 2.0

            # Handle rate limiting with Retry-After
            - when: "{{ _err.kind == 'rate_limit' }}"
              do: retry
              attempts: 10
              delay: "{{ _err.retry_after | default(5) }}"

            # Skip transform errors
            - when: "{{ _task == 'transform' }}"
              do: skip
              set_prev:
                transformed: []
                has_more: false

            # Retry store on deadlock
            - when: "{{ _task == 'store' and _err.kind == 'db_deadlock' }}"
              do: retry
              attempts: 3
              backoff: linear
              delay: 1.0

            # Fail on auth errors
            - when: "{{ _err.kind == 'auth' }}"
              do: fail

            - else:
                do: fail

        finally:
          - next:
              - step: check_pagination
```

### Example 2: Conditional Processing with Jump

```yaml
pipe:
  - validate:
      tool:
        kind: python
        args:
          data: "{{ input }}"
        code: |
          result = {
            'valid': len(data) > 0,
            'data': data
          }

  - process_valid:
      tool:
        kind: python
        args:
          validated: "{{ _prev }}"
        code: |
          if not validated['valid']:
              raise ValueError("Invalid data")
          result = expensive_processing(validated['data'])

  - fallback:
      tool:
        kind: python
        code: |
          result = {'status': 'skipped', 'reason': 'invalid data'}

  - finalize:
      tool:
        kind: python
        args:
          prev: "{{ _prev }}"
        code: |
          result = {'final': prev}

catch:
  cond:
    # Jump to fallback on validation failure
    - when: "{{ _task == 'process_valid' and _err.exception_type == 'ValueError' }}"
      do: jump
      to: fallback

    - else:
        do: fail
```

### Example 3: Heavy Payload Processing

```yaml
pipe:
  - fetch_heavy:
      tool:
        kind: http
        url: "{{ api_url }}/heavy"
        params:
          payload_kb: 100
        output_select:
          strategy: size_threshold
          threshold_kb: 50  # Externalize if > 50KB

  - extract_metadata:
      tool:
        kind: python
        args:
          heavy_data: "{{ _prev }}"
        code: |
          # Only extract metadata, don't keep heavy payload in memory
          result = {
            'count': len(heavy_data.get('items', [])),
            'ids': [i['id'] for i in heavy_data.get('items', [])]
          }

  - store_metadata:
      tool:
        kind: postgres
        query: |
          INSERT INTO metadata (item_count, item_ids)
          VALUES ({{ _prev.count }}, '{{ _prev.ids | tojson }}')

catch:
  cond:
    - when: "{{ _err.retryable }}"
      do: retry
      attempts: 3
    - else:
        do: fail
```

## Pipeline Result

When a pipeline completes, it returns:

```yaml
# Success
{
  "status": "success",
  "_prev": <final task result>,
  "results": {
    "task_1": <task_1 result>,
    "task_2": <task_2 result>,
    ...
  },
  "finally": [...]  # For caller to process
}

# Failure
{
  "status": "failed",
  "_prev": <last successful result>,
  "results": {...},
  "error": {
    "kind": "...",
    "message": "...",
    ...
  },
  "failed_task": "task_name"
}
```

## Integration with Step Transitions

The `finally` block connects pipelines to the broader workflow:

```yaml
pipe:
  - ...tasks...

catch:
  cond:
    - ...error handling...

finally:
  - next:
      - step: next_step
  - vars:
      processed: "{{ _prev.count }}"
```

## Comparison with Standard Step Execution

| Aspect | Standard Steps | Pipeline Execution |
|--------|---------------|-------------------|
| **Execution** | Distributed across workers | Single worker, atomic |
| **Data Passing** | Via event payloads | Direct `_prev` threading |
| **Error Handling** | Per-step case blocks | Centralized `catch.cond` |
| **Retry Scope** | Individual step | Any task in pipeline |
| **Use Case** | Independent operations | Tightly coupled sequences |

## Best Practices

1. **Use pipelines for tightly coupled operations** where failure of one task affects all subsequent tasks (e.g., fetch → transform → store).

2. **Keep pipelines focused** - 3-5 tasks is typical. For longer sequences, consider breaking into multiple steps.

3. **Always include a default `else: fail`** in catch.cond to handle unexpected errors.

4. **Use `set_prev` with skip** to provide sensible defaults when skipping failed tasks.

5. **Prefer specific error matching** over broad `_err.retryable` checks when you need different handling per task.

6. **Consider `output_select`** on HTTP tasks that may return large responses to prevent memory issues.

## Related Documentation

- [Result Storage](result_storage.md) - How large results are externalized
- [Error Classification](../reference/errors.md) - Full error kind reference
- [Retry Mechanism](retry_mechanism.md) - Step-level retry patterns
- [Pagination](pagination.md) - Pagination patterns using pipelines
