# Postgres step

Execute SQL against Postgres using a configured `auth` connection.

What it does
- Runs DDL/DML/queries on a Postgres database.
- Suitable for schema management, inserts/updates, and simple reads.

Required keys
- type: postgres
- auth: reference to a credential
- command or sql: SQL text to execute

Common optional keys
- assert: Validate inputs/outputs
- save: Capture driver response or query results (engine-dependent)

Templating and JSON
- Use templating for values from context (e.g., `{{ execution_id }}`, `{{ city.name }}`).
- For JSON payloads, wrap with $$...$$ or use tojson to avoid quoting issues.

Usage patterns (fragments)
- Ensure table exists (idempotent)
  ```yaml
  - step: write
    type: postgres
    auth: app_db
    command: |
      CREATE TABLE IF NOT EXISTS public.weather_http_raw (
        id TEXT PRIMARY KEY,
        execution_id TEXT,
        iter_index INTEGER,
        city TEXT,
        url TEXT,
        elapsed DOUBLE PRECISION,
        payload TEXT,
        created_at TIMESTAMPTZ DEFAULT now()
      );
  ```

- Upsert with templated values
  ```yaml
  - step: write
    type: postgres
    auth: app_db
    sql: |
      insert into public.items(id, name, content)
      values
        ({{ get_snowflake_id() }}, '{{ it.name }}', $${{ content | tojson }}$$)
      on conflict (id) do update set
        name = excluded.name,
        content = excluded.content;
  ```

- Per-item save from iterator task
  ```yaml
  - step: write
    type: postgres
    auth: app_db
    sql: |
      insert into public.items(id, name, content)
      values
        ({{ get_snowflake_id() }}, '{{ it.name }}', $${{ content | tojson }}$$)
      on conflict (id) do update set
        name = excluded.name,
        content = excluded.content;
    save:
      - name: write_result
        data: "{{ this.data }}"
  ```

Tips
- Prefer CREATE TABLE IF NOT EXISTS and ON CONFLICT for idempotency.
- Keep transactions small; batch writes where practical.
- Define and reference auth entries in the playbook header.

Retry
- Use `retry` for transient connection or lock errors.
- Context vars: `error` (error message), `success` (bool if adapter sets), `attempt`.
```yaml
retry:
  max_attempts: 3
  initial_delay: 1.0
  backoff_multiplier: 2.0
  retry_when: "{{ error != None or success == False }}"
```
See `retry.md` for details.
