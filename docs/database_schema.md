# NoETL Database Schema and Setup

This document describes the NoETL database schema, where the canonical DDL lives, and the supported ways to initialize or reset the schema across environments (local, Docker/Kubernetes, and CI).

## Overview

NoETL uses Postgres for event‑sourcing, queueing and runtime metadata. The schema is created in a dedicated schema (default: `noetl`). Key components:

- Event sourcing: `noetl.event_log`
- Task queue: `noetl.queue`
- Playbook/workflow metadata: `noetl.catalog`, `noetl.workload`, `noetl.workflow`, `noetl.transition`, `noetl.workbook`
- Runtime registry: `noetl.runtime`
- Error tracking: `noetl.error_log`
- Credentials (optional): `noetl.credential`

The event log column `timestamp` has a default of `CURRENT_TIMESTAMP` and is non‑null in the canonical DDL. New events inserted by the API also set the timestamp on write.

## Canonical DDL location as a single source of truth

- Packaged with the Python wheel:
  - `noetl/database/ddl/postgres/schema_ddl.sql`
- Stays consistent across environments (venv, Docker, Kubernetes), and can be applied via the NoETL CLI.

A source copy is kept under `scripts/database/postgres/schema_ddl.sql` for reference and bootstrapping in legacy environments, but the packaged DDL inside the `noetl` package is authoritative.

## Applying the schema

### Using the NoETL CLI (recommended)

- apply packaged DDL:
  - `noetl db apply-schema`
- apply a custom DDL file:
  - `noetl db apply-schema --file noetl/database/ddl/postgres/schema_ddl.sql`
- role/schema best‑effort:
  - `noetl db apply-schema --ensure-role`

The CLI uses the admin connection string from your environment/config. Required environment (typically via `.env`):

- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`
- `POSTGRES_USER`, `POSTGRES_PASSWORD`
- `NOETL_USER`, `NOETL_PASSWORD`, `NOETL_SCHEMA`

### From the Makefile

- Reset and re-apply the schema in a running Postgres instance:
  - `make postgres-reset-schema`
  - Drops the `noetl` schema and then runs `noetl db apply-schema --ensure-role`.
  - Falls back to `psql -f noetl/database/ddl/postgres/schema_ddl.sql` if the CLI can’t be used.

### Server‑assisted initialization 

- Start the API server and initialize the schema:
  - `noetl server start --init-db`
- Via Makefile:
  - `NOETL_INIT_DB=true make start-server`
  - Backward compatibility: `NOETL_SCHEMA_VALIDATE=true make start-server`

By default, the server does NOT initialize the schema unless `--init-db` is explicitly passed or set in the env flag.

## Kubernetes

### Clean flow (preferred)

- Job to apply schema using the packaged DDL:
  - `k8s/postgres/noetl-apply-schema.yaml`
  - Runs `noetl db apply-schema --ensure-role` with retries and a TTL for cleanup.
  - Pulls connection/env values from `postgres-config` and `postgres-secret`.

Usage:

```
# After Postgres is deployed and ready
kubectl apply -f k8s/postgres/noetl-apply-schema.yaml
kubectl logs job/noetl-apply-schema -n postgres
```

### Deployment manifest

- Only Postgres server config `Postgres.conf` is mounted from `postgres-config-files`.

## Validating setup

- Check that `event_log.timestamp` has a default:

```
psql -c "SELECT column_default
          FROM information_schema.columns
         WHERE table_schema='noetl'
           AND table_name='event_log'
           AND column_name='timestamp';"
```

- Run a quick playbook and export logs:

```
make noetl-execute PLAYBOOK=examples/test/simple_test
make export-execution-logs ID=<execution_id>
cat logs/event_log.json | head
```

Expect:
- Non‑null `timestamp` values
- A single `execution_complete` for the run

## Table summary

- `noetl.event_log`: event sourcing for executions; `timestamp` (default current time), `event_type`, `node_*`, `context`, `result`.
- `noetl.queue`: durable queue for worker orchestration; status, lease, attempts.
- `noetl.workload`: initial payload by `execution_id`.
- `noetl.workflow`/`noetl.transition`: workflow and transitions materialized from playbooks.
- `noetl.workbook`: workbook action metadata.
- `noetl.catalog`: registered resources (playbooks, datasets, etc.).
- `noetl.runtime`: server/worker runtime registry + heartbeat.
- `noetl.error_log`: structured error records for diagnostics.

## Notes

- Ownership is set to the `noetl` role where relevant. Grant statements are conservative and can be adjusted for the security model.
- For migrations/versioning, consider maintaining a `noetl/database/migrations` directory and a lightweight migration runner in a future iteration.

