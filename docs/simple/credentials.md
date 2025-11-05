# Credentials (unified auth)

Provide connection and secret parameters to steps without hardcoding sensitive values in playbooks.

What they are
- JSON documents registered into the NoETL catalog (credential store)
- Referenced in playbooks via `auth:` (single) or auth mapping (multi-credential)
- Exposed to steps/plugins with a consistent key/value interface

Basic JSON structure
```json
{
  "name": "pg_k8s",
  "type": "postgres",
  "description": "Kubernetes Postgres connection for NoETL workers",
  "tags": ["k8s", "postgres", "worker"],
  "data": {
    "db_host": "postgres.postgres.svc.cluster.local",
    "db_port": "5432",
    "db_user": "demo",
    "db_password": "demo",
    "db_name": "demo_noetl"
  }
}
```

Registration
```bash
# Register via CLI
noetl credential register tests/fixtures/credentials/pg_k8s.json

Referencing in steps (single credential)
```yaml
- step: setup_pg_table
  type: postgres
  auth: "{{ workload.pg_auth }}"
  command: "CREATE TABLE IF NOT EXISTS public.test (...);"
```

Multi-credential mapping (DuckDB attaching Postgres + Cloud)
```yaml
- step: aggregate_with_duckdb
  type: duckdb
  auth:
    pg_db:
      source: credential
      type: postgres
      key: "{{ workload.pg_auth }}"
    gcs_secret:
      source: credential
      type: hmac
      key: gcs_hmac_local
      scope: gs://{{ workload.gcs_bucket }}
  commands: |
    INSTALL postgres; LOAD postgres;
    ATTACH '' AS pg_db (TYPE postgres, SECRET pg_db);
```

Auth block variants
- Simple reference: `auth: pg_k8s`
- Templated: `auth: "{{ workload.pg_auth }}"`
- Mapped (dictionary with aliases): nested objects describing source/type/key (+ optional scope)

Usage patterns
- Postgres / Snowflake steps: pass credential key directly
- DuckDB: map multiple credentials for attachments and cloud storage
- Transfer steps: `auth.sf` and `auth.pg` keys for bidirectional movement

Security tips
- Keep secrets only in credential JSON or external secret manager; avoid placing passwords in `workload:`.
- Use tags (`"tags": ["env:dev", "team:data"]`) for filtering and governance.
- Rotate passwords by updating and re-registering the credential (same name).
- Prefer minimal privilege accounts (least privilege principle).

Retry & credential errors
- If connection fails (`error` set) and a `retry` block exists, subsequent attempts reuse the same credential; validate fields before enabling high attempt counts.

Common pitfalls
- Misspelled credential name → lookup failure
- Using old environment variables after migrating to unified auth
- Forgetting required fields (e.g., `sf_account`) for Snowflake
- Wrong scope for cloud storage operations (ensure `scope` matches bucket prefix)

See also
- `steps/duckdb.md` (auth mapping example)
- `steps/snowflake.md` (Snowflake specifics)
- `retry.md` (handling transient auth/connection failures)
