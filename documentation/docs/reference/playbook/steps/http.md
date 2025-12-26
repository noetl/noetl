# HTTP step

Make HTTP requests and bind responses into the playbook context.

What it does
- Sends a request (method, endpoint, headers, data) and parses the response into the step context.
- Inside the step (or an iterator task), the parsed response is available as `this.data`.
- In later steps, access it via `<step_name>.data`.

Required keys
- tool: http
- endpoint: URL to call (templating allowed)

Common optional keys
- method: GET (default), POST, PUT, DELETE, ...
- headers: Map of request headers
- data: Request parameters/body (GET -> query params, POST -> JSON body)
- timeout: Request timeout in seconds
- assert: Validate inputs/outputs
  - expects: list of inputs to check before call
  - returns: list of fields to check after call (e.g., `data.url`, `data.elapsed`, `data.payload`)
- sink: Persist all or a projection of the response to a variable or storage

Inputs and templating
- Reference earlier context: `{{ workload.base_url }}`, `{{ previous.data.id }}`.
- Use simple expressions and filters; for JSON payloads prefer `| tojson` when embedding.

Outputs and context
- Success response becomes `this.data` within the step, and `<step>.data` later.
- In a loop, guard per-item saves: `this is defined and this.data is defined` to avoid nulls on failures.

Usage patterns
- GET with query params and response contract
  - method: GET
  - data: key/value become query parameters
  - assert.returns to ensure fields exist in the parsed response
- POST with JSON body and selective save
  - method: POST
  - data: becomes JSON body
  - sink: pick only needed fields (e.g., `this.data.id`)
- Iterator per-item call with upsert
  - Put the http step inside an iterator `task`
  - Use `http_loop.result_index` to build stable ids with `execution_id`
  - Save each item to Postgres (mode: upsert) with guarded projections

Examples (fragments)
- GET with params and headers
```
  # ...existing code...
  method: GET
  endpoint: "{{ workload.base_url }}/forecast"
  headers:
    User-Agent: "NoETL Demo/1.0"
  data:
    latitude: 51.51
    longitude: -0.13
    hourly: temperature_2m
    forecast_days: 1
  assert:
    expects: [ data.latitude, data.longitude, data.hourly, data.forecast_days ]
    returns: [ data.url, data.elapsed, data.payload ]
```

- POST JSON with selective save
```
  # ...existing code...
  method: POST
  endpoint: "https://api.example.com/items"
  headers:
    Content-Type: application/json
  data:
    name: "{{ previous.data.name }}"
    tags: "{{ previous.data.tags }}"
  sink: { name: created_id, data: "{{ this.data.id }}" }
```
- Inside iterator: guarded per-item upsert
```
  # ...existing code...
  type: iterator
  element: item
  collection: "{{ workload.items }}"
  task:
    tool: http
    endpoint: "https://api.example.com/{{ item.id }}"
    sink:
      data:
        id: "{{ execution_id }}:{{ item.id }}:{{ fetch_each.result_index }}"
        payload: "{{ (this.data | tojson) if this is defined and this.data is defined else '' }}"
      tool: postgres
      auth: pg_local
      table: public.items_http
      mode: upsert
      key: id
```
Failure modes and tips
- Timeouts or non-2xx responses fail the step; use `assert` to catch missing fields early.
- Prefer saving a projection over entire payloads to reduce storage size.
- Keep `endpoint` templating simple and well-quoted to avoid YAML parsing issues.

Retry
- Add a `retry:` block to handle transient HTTP errors or specific status codes.
- Context vars available to expressions: `status_code`, `error`, `attempt`, `max_attempts`.
- Typical pattern: retry on 5xx, stop early on 200.
```yaml
retry:
  max_attempts: 3
  initial_delay: 0.5
  backoff_multiplier: 2.0
  retry_when: "{{ status_code >= 500 and status_code < 600 }}"
```
See `retry.md` for full syntax (including `stop_when`).
