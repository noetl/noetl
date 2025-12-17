# Snowflake step

Execute Snowflake SQL (DDL/DML/query) using unified credentials.

What it does
- Runs one or more SQL statements against Snowflake (CREATE, INSERT, SELECT, MERGE, etc.)
- Returns query results (for SELECT) or execution status (for DDL/DML) in `this.data`
- Supports JSON/VARIANT usage via `PARSE_JSON(...)` and automatic type mapping when consumed later

Required keys
- `type: snowflake`
- `auth`: credential key or mapping (e.g. `{{ workload.sf_auth }}`)
- `command` or `sql`: Snowflake SQL text

Common optional keys
- `assert`: input/output validation (`expects`, `returns`)
- `save`: persist outputs (event log, postgres, etc.)
- `retry`: bounded re-attempt for transient connection / warehouse errors (see `retry.md`)
- `desc`: human description

Auth pattern
```yaml
- step: create_sf_database
  type: snowflake
  auth: "{{ workload.sf_auth }}"
  command: |
    CREATE DATABASE IF NOT EXISTS TEST_DB;
    USE DATABASE TEST_DB;
    USE SCHEMA PUBLIC;
```
Registered credential must provide Snowflake connection fields (`sf_account`, `sf_user`, `sf_password`, `sf_warehouse`, etc.).

JSON / VARIANT handling
- Use `PARSE_JSON('{"key": "value"}')` to insert structured data
- When later transferring to Postgres, VARIANT → JSONB conversion occurs automatically (see `snowflake_transfer` examples)

Examples

DDL + schema selection:
```yaml
- step: setup_sf_table
  type: snowflake
  auth: "{{ workload.sf_auth }}"
  command: |
    CREATE OR REPLACE TABLE TEST_DATA (
      id INTEGER PRIMARY KEY,
      name STRING,
      value NUMERIC(10,2),
      created_at TIMESTAMP_TZ,
      metadata VARIANT
    );
```

Populate table:
```yaml
- step: seed_sf
  type: snowflake
  auth: "{{ workload.sf_auth }}"
  command: |
    INSERT INTO TEST_DATA
    SELECT 1, 'Record 1', 100.50, CURRENT_TIMESTAMP(), PARSE_JSON('{"type": "test", "batch": 1}')
    UNION ALL
    SELECT 2, 'Record 2', 200.75, CURRENT_TIMESTAMP(), PARSE_JSON('{"type": "test", "batch": 1}');
```

Query with verification:
```yaml
- step: verify_sf_data
  type: snowflake
  auth: "{{ workload.sf_auth }}"
  command: |
    SELECT COUNT(*) AS row_count, MIN(id) AS min_id, MAX(id) AS max_id
    FROM TEST_DATA;
  assert:
    returns: [ data.row_count, data.min_id, data.max_id ]
```

Retry on transient failures:
```yaml
- step: query_sf
  type: snowflake
  auth: "{{ workload.sf_auth }}"
  command: "SELECT * FROM TEST_DATA ORDER BY id"
  retry:
    max_attempts: 3
    initial_delay: 1.0
    backoff_multiplier: 2.0
    retry_when: "{{ error != None }}"
```

Interaction with snowflake_transfer
- Use snowflake steps for setup (CREATE TABLE, seed data) and verification (SELECT aggregates)
- Use `snowflake_transfer` steps for bulk streaming into / out of Snowflake
- Keep transfer-related logic (chunk_size, mode) in dedicated `snowflake_transfer` steps; Snowflake standard steps stay lightweight

See also
- `snowflake_transfer_quickstart.md` (bulk streaming)
- `retry.md` (retry policy fields)
- `steps/save.md` (saving results)