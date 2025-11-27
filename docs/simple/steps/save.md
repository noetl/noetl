# Save block

Persist step outputs to named variables or external storages (event log, postgres, duckdb, http webhook, custom python) with a unified schema.

Two shapes
1. Variable save (in‑memory context)
2. Storage save (delegated to a storage adapter)

Minimal variable sink:
```yaml
- step: fetch
  type: http
  endpoint: https://example.com
  sink: { name: page, data: "{{ this.data }}" }
```

Iterator aggregated variable sink:
```yaml
- step: http_loop
  type: iterator
  # ...iterator config...
  sink:
    - name: http_loop
      data: "{{ this.result }}"
```

Storage delegation (flat form):
```yaml
sink:
  tool: postgres
  auth: app_db
  table: public.items
  mode: upsert          # insert | upsert | replace (engine defined)
  key: id               # required for upsert
  data:
    id: "{{ execution_id }}:{{ item.id }}"
    payload: "{{ (this.data | tojson) if this is defined and this.data is defined else '' }}"
```

Storage delegation (nested form):
```yaml
sink:
  storage:
    type: postgres
    table: public.items
    mode: upsert
    key: id
    auth: app_db
  data:
    id: "{{ execution_id }}:{{ user.id }}"
    name: "{{ user.name }}"
```

Supported storage types (simple docs scope)
- event / event_log: emit result into execution event log (default when only name+data)
- postgres: insert/upsert rows
- duckdb: run commands or stage data (often with `commands:` in storage config)
- http: POST/PUT JSON to an endpoint (webhook style)
- python: invoke inline custom save code (advanced transformations before persistence)

Delegation examples
Event log (simple variable archiving):
```yaml
sink:
  storage: event_log
  data: "{{ result.data }}"
```

Postgres flat structure (from simple save test):
```yaml
sink:
  tool: postgres
  auth: "{{ workload.pg_auth }}"
  table: simple_test_flat
  data:
    test_id: "{{ result.data.record_id }}"
    test_name: "{{ result.data.description }}"
    test_value: 42
```

Postgres nested + upsert:
```yaml
sink:
  storage:
    type: postgres
    table: simple_test_nested
    mode: upsert
    key: test_id
    auth: "{{ workload.pg_auth }}"
  data:
    test_id: "{{ result.data.nested_id }}"
    test_name: "nested_structure_test"
    execution_id: "{{ execution_id }}"
```

DuckDB analytics staging (delegation test):
```yaml
sink:
  storage:
    type: duckdb
    commands: |
      CREATE OR REPLACE TABLE test_duckdb AS 
      SELECT 'delegation_test' as test_type, 'duckdb_working' as status;
      SELECT * FROM test_duckdb;
  data: "{{ result.data }}"
```

HTTP webhook:
```yaml
sink:
  storage:
    type: http
    url: https://httpbin.org/post
    method: POST
    headers: { Content-Type: application/json }
  data: "{{ result.data }}"
```

Custom python sink:
```yaml
sink:
  storage:
    type: python
    code: |
      def main(data):
          # transform or route data
          print("Storing", data.keys())
          return {"status": "ok"}
  data: "{{ result.data }}"
```

Iterator per-item guarded save (from http_duckdb_postgres example):
```yaml
sink:
  tool: postgres
  args:                        # engine-specific optional grouping
    id: "{{ execution_id }}:{{ city.name }}:{{ http_loop.result_index }}"
    execution_id: "{{ execution_id }}"
    iter_index: "{{ http_loop.result_index }}"
    city: "{{ city.name }}"
    url: "{{ this.data.url if this is defined and this.data is defined else '' }}"
    elapsed: "{{ (this.data.elapsed | default(0)) if this is defined and this.data is defined else 0 }}"
    payload: "{{ (this.data | tojson) if this is defined and this.data is defined else '' }}"
  auth: "{{ workload.pg_auth }}"
  table: public.weather_http_raw
  mode: upsert
  key: id
```

Large payload tips
- Store only required fields; consider hashing or summarizing large JSON blobs.
- Use `| tojson` + server-side compression (DuckDB Parquet COPY, etc.) for analytics outputs.
- For big lists, prefer pushing aggregation logic into SQL (DuckDB/Postgres) instead of saving raw arrays repeatedly.

Guards & defensive expressions
- Use `this is defined and this.data is defined` before dereferencing nested fields inside loops.
- Default filters: `{{ value | default(0) }}` or `{{ obj.field | default('') }}` to prevent null propagation.

Choosing flat vs nested form
- Flat (single-level keys) is concise for simple inserts.
- Nested object under `storage:` is clearer when specifying multiple storage parameters (mode, key, auth, commands).

Retry interaction
- `retry` wraps the producing step; save executes only on each attempt's execution result. Engine may attempt save after each successful attempt; design idempotent save logic (use deterministic IDs / upserts).

Common pitfalls
- Forgetting `key` for upsert mode → engine error.
- Quoting JSON incorrectly; use `| tojson` or dollar-quoted strings inside SQL steps instead of raw interpolation.
- Large unfiltered payloads bloating event log; project only needed fields.

See also
- `postgres.md`, `duckdb.md`, `http.md` for action-specific considerations
- `retry.md` for retry semantics (ensure idempotent saves)
