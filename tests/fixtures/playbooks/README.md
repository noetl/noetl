# Examples: Test Playbooks

This folder contains small, fast playbooks you can use to validate a local NoETL setup end‑to‑end. They cover Python, HTTP, Postgres, and Save flows, and demonstrate the unified step payload convention using `input` (with `payload` and `with` still supported for backward compatibility).

## Prerequisites

- Python environment with NoETL installed (dev):
  - `make create-venv && make install-dev`
- A running Postgres you can write to. The repo’s default expects:
  - host: `localhost`
  - port: `30543`
  - user: `demo`
  - password: `demo`
  - database: `demo_noetl`
- Local env configured (see `.env`). The defaults in this repo work with the dev Postgres above.

## Start server and workers

- Option A (one command):
  - `make noetl-start`
- Option B (manual):
  - `make start-server`
  - `make start-workers`

Check server status: `make server-status`

## Register examples and credentials

- Register all example playbooks:
  - `make register-examples`
- Register test credentials (installs pg_local):
  - `make register-test-credentials`
  - or individually: `make register-credential FILE=examples/test/credentials/pg_local.json`

## Running the tests

Use the helper target that prints the execution acceptance and exports logs automatically when successful:

- `make noetl-execute PLAYBOOK=<path>`

Where `<path>` is one of:

- `examples/test/simple_test`
- `examples/test/loop_http_test`
- `examples/test/loop_http_test_sequential`
- `examples/test/postgres_save_simple`
- `examples/test/postgres_save_simple2`
- `examples/test/test_postgres_storage`

### 1) Simple Test

- Run: `make noetl-execute PLAYBOOK=examples/test/simple_test`
- Expect: a quick execution that emits `execution_complete` with the message from the start step.
- Inspect logs (exported automatically): `logs/event_log.json`

### 2) HTTP Loop (async) and (sequential)

- Run:
  - `make noetl-execute PLAYBOOK=examples/test/loop_http_test`
  - `make noetl-execute PLAYBOOK=examples/test/loop_http_test_sequential`
- Expect: an aggregate result with per‑city metrics and counts.
- Inspect: `logs/event_log.json` shows `aggregate_results` output and a final summary at `step: end`.

### 3) Postgres Save (simple) and (simple2)

These create (if not present) and write into `public.postgres_save_demo` using the `pg_local` credential.

- Run:
  - `make noetl-execute PLAYBOOK=examples/test/postgres_save_simple`
  - `make noetl-execute PLAYBOOK=examples/test/postgres_save_simple2`
- Verify in Postgres:
  - `export PGPASSWORD=demo`
  - `psql -h localhost -p 30543 -U demo -d demo_noetl -c "SELECT id, message, created_at FROM public.postgres_save_demo ORDER BY created_at DESC LIMIT 5"`
- Expect: a new row per execution; `id` equals the execution id and `message` equals `Hello Save`.

### 4) Test Postgres Storage

This stores rows into `weather_alert_summary` and returns a short preview.

- Run: `make noetl-execute PLAYBOOK=examples/test/test_postgres_storage`
- Verify in Postgres:
  - `psql -h localhost -p 30543 -U demo -d demo_noetl -c "SELECT id, alert_cities, alert_count, created_at FROM weather_alert_summary ORDER BY id DESC LIMIT 5"`
- Expect: recent rows with the JSON array of cities and an integer count.

## Exporting and inspecting logs manually

If you need to re‑export for a specific execution:

- `make export-event-log ID=<execution_id>`
- `make export-queue ID=<execution_id>`

Outputs are written to:

- `logs/event_log.json` — all events for the execution
- `logs/queue.json` — queue rows for the execution

## Troubleshooting

- Credential not found or DB connection error:
  - Ensure you ran `make register-test-credentials` and the server is up.
  - Confirm Postgres variables in `.env` match your instance (host/port/user/password/db).
- HTTP failures:
  - Network issues can cause errors for the loop tests. Re‑run or set a different city set if needed.
- Nothing happens after acceptance:
  - Ensure workers are running: `ps aux | grep 'noetl worker' | grep -v grep`
  - Check server and worker logs under `logs/`.

## Clean up

- Stop workers and server:
  - `make noetl-stop`
- Optional DB cleanup:
  - Remove tables created during tests if you wish (e.g., `DROP TABLE public.postgres_save_demo;` and `DROP TABLE weather_alert_summary;`).

