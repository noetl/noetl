# Retry block

Add conditional, bounded retry logic to an action step (http, python, postgres, duckdb, workbook task, iterator task inner action).

What it is
- Inline policy under a step: `retry:`
- Evaluates expressions after each attempt using attempt-scoped context variables
- Controls when to schedule another attempt and when to stop early

Fields
- `max_attempts` (int, required): Upper bound (includes the first attempt). Minimum 1.
- `initial_delay` (float, optional, seconds): Base sleep before the 2nd attempt (default 0).
- `backoff_multiplier` (float, optional): Multiply previous delay (default 2.0 if delay provided, else 1.0)
- `max_delay` (float, optional): Cap on computed delay
- `retry_when` (string, Jinja expression, optional): Retry if expression is truthy. If omitted, default retry condition is any error (error != None)
- `stop_when` (string, Jinja expression, optional): Stop early (treat as success) when truthy, even if `retry_when` would also match

Attempt context variables (available to expressions)
- `attempt` (int, 1-based)
- `max_attempts` (int)
- `error` (string or null): Last error message (python exception, HTTP/network error, SQL error). Null on success.
- `status_code` (int or null): HTTP status code if http step
- `success` (bool or null): Postgres / DuckDB execution status or custom plugin success flag
- `result` / `data`: Last attempt returned data (may be partial or absent)
- Plugin-specific fields may also be present (e.g., duration, rows_affected)

Order of evaluation
1. Run attempt
2. Populate context (error, status_code, success, data)
3. Evaluate `stop_when`; if true → finish (success path)
4. Evaluate `retry_when`; if true and attempt < max_attempts → schedule next attempt after backoff delay
5. Otherwise finish (success if no error, failure if error present)

Backoff calculation
```
next_delay = min(max_delay, initial_delay * (backoff_multiplier ** (attempt-1)))
```
If `initial_delay` not set or zero, delay is zero (no sleep) unless you explicitly configure it.

Patterns
- Retry on any 5xx HTTP status:
```yaml
retry:
  max_attempts: 3
  initial_delay: 0.5
  backoff_multiplier: 2.0
  retry_when: "{{ status_code >= 500 and status_code < 600 }}"
```

- Retry until HTTP 200 then stop immediately when OK (avoids extra delay):
```yaml
retry:
  max_attempts: 3
  initial_delay: 0.5
  backoff_multiplier: 1.5
  retry_when: "{{ status_code != 200 }}"
  stop_when: "{{ status_code == 200 }}"
```

- Retry Python step while exception raised:
```yaml
retry:
  max_attempts: 5
  initial_delay: 0.2
  backoff_multiplier: 1.5
  max_delay: 2.0
  retry_when: "{{ error != None }}"
```

- Retry Postgres on connection/query failure or explicit unsuccessful flag:
```yaml
retry:
  max_attempts: 3
  initial_delay: 1.0
  backoff_multiplier: 2.0
  retry_when: "{{ error != None or success == False }}"
```

- Retry DuckDB query when engine signals error (generic fallback):
```yaml
retry:
  max_attempts: 3
  initial_delay: 0.5
  backoff_multiplier: 1.5
  retry_when: "{{ error != None }}"
```

Edge cases & tips
- Always bound `max_attempts`; no unbounded loops.
- Use `stop_when` to short-circuit success conditions separate from error detection.
- Guard expressions: e.g., `{{ status_code is defined and status_code >= 500 }}` if unsure of presence.
- Capture retry metrics from events (attempt number appears in emitted events for observability).
- Keep delays modest in tests to keep execution time low.

Failure outcome
- If final attempt ends with `error` and `stop_when` not triggered, the step fails and the workflow follows failure semantics (logged event, no further `next` unless engine supports compensation logic).

See also
- `workflow.md` (step keys) for placement
- Individual step docs for plugin-specific fields
```