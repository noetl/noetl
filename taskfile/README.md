NoETL Taskfile README

Overview
- This folder contains task definitions used with the `go-task` runner (`Taskfile`). The tasks in `taskfile/noetl.yaml` help you quickly start, stop, and inspect a local NoETL development stack.
- Typical usage:
  - `task noetl-local-start`
  - `task ui-dev`
  - `task debug-status`
  - `task debug-stop-all`

How it works
- The tasks defined here are included by the project’s root Taskfile (`taskfile.yml`). You should run `task` commands from the project root.
- Logs and PID files are written to the `logs/` directory.

Prerequisites
- A POSIX shell environment (macOS/Linux or WSL).
- Python available (ideally a `.venv` with dependencies installed).
- `uvicorn` installed in either the active virtualenv or `PATH` if you plan to run the server task via uvicorn.
- `lsof` or `fuser` available for port-kill tasks.

Common environment variables
- `ENV_FILE`: Path to an env file to source before starting processes. If not set, tasks auto-prefer `.env.pycharm` when present, otherwise `.env`.
- `NOETL_API_HOST` / `NOETL_HOST`: Host bind address for the API server (default `0.0.0.0`).
- `NOETL_API_PORT` / `NOETL_PORT`: Port for the API server (default `8083`).
- `NOETL_API_URL`: Worker API base URL (defaults to `http://localhost:8083` in `worker-debug`).
- `NOETL_RUN_MODE`: Set to `worker` by `worker-debug` when launching the worker dispatcher.
- `VITE_API_BASE_URL`: UI dev server API base URL. If unset, `task ui-dev` will auto-detect a running local API (prefers `http://localhost:8083`, falls back to `http://localhost:8000`).

Tasks

1) **server-debug** (aliases: `sdbg`)
- What it does: Starts the NoETL API server in debug mode as a background daemon via `uvicorn`, writing logs and a PID file under `logs/`.
- Logs: `logs/server-debug.log`
- PID: `logs/server-debug.pid`
- Host/Port: Uses `NOETL_API_HOST`/`NOETL_HOST` and `NOETL_API_PORT`/`NOETL_PORT`; falls back to `0.0.0.0:8083`.
- Preflight: If the target port is in use, attempts to gracefully kill the process(es) occupying it.
- Usage examples:
  - `task server-debug`
  - `ENV_FILE=.env task server-debug`
  - `NOETL_API_PORT=8090 task server-debug`
- Notes:
  - Prefers `.venv/bin/python` if present; otherwise uses system `python`.
  - Falls back to system `uvicorn` if not importable from Python.

2) **server-debug-stop** (aliases: `sdbg-stop`)
- What it does: Stops the background server started by `server-debug` using the saved PID.
- Safe behavior: If the PID is missing or the process is already stopped, it exits cleanly.
- Usage: `task server-debug-stop`

3) **server-kill-8083** (aliases: `sk83`)
- What it does: Kills any process listening on the configured API port (defaults to `8083` or `NOETL_API_PORT`/`NOETL_PORT` if set).
- Tools: Uses `lsof` when available, otherwise `fuser`.
- Usage: `task server-kill-8083`

4) **kill-port**
- What it does: Kills any process listening on a specified TCP port.
- Required input: `PORT` (positional via variable). Example: `task kill-port PORT=8090`
- Tools: Uses `lsof` when available, otherwise `fuser`.

5) **worker-debug** (aliases: `wdbg`)
- What it does: Starts the NoETL worker in debug mode as a background daemon via the CLI entry point (`python -m noetl.main worker start`).
- Logs: `logs/worker-debug.log`
- PID: `logs/worker-debug.pid`
- Environment:
  - Ensures `NOETL_API_URL` is set (defaults to `http://localhost:8083` if unset)
  - Exports `NOETL_RUN_MODE=worker`
- Usage examples:
  - `task worker-debug`
  - `NOETL_API_URL=http://localhost:9000 task worker-debug`

6) **worker-debug-stop** (aliases: `wdbg-stop`)
- What it does: Stops the background worker started by `worker-debug` using the saved PID.
- Safe behavior: If the PID is missing or the process is already stopped, it exits cleanly.
- Usage: `task worker-debug-stop`

7) **debug-stop-all** (aliases: `stop-all`)
- What it does: Stops both server and worker started by the debug tasks.
- Usage: `task debug-stop-all`

8) **debug-kill-all** (aliases: `kill-all`)
- What it does: Force kills any orphan server/worker processes related to NoETL, and cleans up PID files.
- Usage: `task debug-kill-all`

9) **debug-status** (aliases: `status`)
- What it does: Displays the current status of the server and worker background processes, referencing their PID files and log locations.
- Usage: `task debug-status`

10) **noetl-local-start** (aliases: `local-start`, `lstart`)
- What it does: Convenience task to start a full local stack for development: server first, waits 5 seconds, then worker.
- Output: Prints service endpoints and log pointers for convenience.
- Usage examples:
  - `task noetl-local-start`
  - `ENV_FILE=.env NOETL_API_PORT=8090 task noetl-local-start`

11) **ui-dev** (aliases: `ui`, `ui-start`)
- What it does: Starts the NoETL UI locally using the Vite dev server and connects to the local NoETL server.
- API connection: Connects to the local NoETL server at `http://localhost:8083/api` by default.
  - Health check: Verifies that the NoETL server is running and responding before starting the UI.
  - If the server is not running, displays a warning with instructions to start it using `task server-debug`.
- Environment:
  - `VITE_API_BASE_URL` (optional): Manually override the API base URL used by the UI. Must include the `/api` path.
- Usage examples:
  - `task ui-dev` (connects to http://localhost:8083/api)
  - `VITE_API_BASE_URL=http://localhost:9000/api task ui-dev`
- Prerequisites:
  - NoETL server must be running on port 8083. Start with `task server-debug` if needed.
- Notes:
  - The UI dev server listens on port 3001 by default (or next available port if 3001 is busy).
  - You need Node.js and npm installed. The task installs UI deps automatically if missing.

12) **noetl-local-setup-test-environment** (aliases: `local-setup-test`, `lste`)
- What it does: Complete test environment setup using the local NoETL service on port 8083.
- Process:
  1. Verifies NoETL server is running on port 8083
  2. Resets PostgreSQL schema using `postgres-reset-schema`
  3. Registers test credentials (`pg_local.json`, `gcs_hmac_local.json`)
  4. Registers all test playbooks from `tests/fixtures/playbooks/`
- Prerequisites:
  - NoETL server must be running on port 8083. Start with `task server-debug` if needed.
  - Update `tests/fixtures/credentials/gcs_hmac_local.json` with valid GCS HMAC credentials.
- Usage examples:
  - `task noetl-local-setup-test-environment`
  - `task local-setup-test` (alias)
- Notes:
  - This is the local equivalent of the Kubernetes-based `setup-test-environment`.
  - Test playbooks use templated `pg_auth` that defaults to `pg_k8s` but can be overridden at runtime.
  - Use `task test-create-tables-local` and `task test-execute-local` for local testing.

13) **test-create-tables-local** (aliases: `tctl`)
- What it does: Creates database tables required for save storage tests using local postgres credentials.
- Process:
  1. Verifies NoETL server is running on port 8083
  2. Executes the `create_tables` playbook with `pg_auth=pg_local` override
- Prerequisites:
  - NoETL server running on port 8083
  - Test environment setup completed (`task local-setup-test`)
- Usage: `task test-create-tables-local`

14) **test-execute-local** (aliases: none)
- What it does: Executes any test playbook with local postgres credentials.
- Parameters: `PLAYBOOK` (required) - path to the playbook to execute
- Process:
  1. Verifies NoETL server is running on port 8083
  2. Executes the specified playbook with `pg_auth=pg_local` override
- Prerequisites:
  - NoETL server running on port 8083
  - Test environment setup completed (`task local-setup-test`)
- Usage examples:
  - `task test-execute-local PLAYBOOK=tests/fixtures/playbooks/save_storage_test/save_simple_test`
  - `task test-execute-local PLAYBOOK=tests/fixtures/playbooks/http_duckdb_postgres/http_duckdb_postgres`

15) **noetl-local-full-setup** (aliases: `local-full-setup`, `lfs`)
- What it does: Complete one-command setup for local NoETL development environment.
- Process:
  1. Sets up test environment (credentials, playbooks, schema reset)
  2. Stops any existing services and starts fresh server + worker
  3. Creates database tables for testing
  4. Displays service status and next steps
- Prerequisites:
  - Update `tests/fixtures/credentials/gcs_hmac_local.json` with valid GCS HMAC credentials
- Usage: `task noetl-local-full-setup` or `task lfs`
- Notes:
  - This is the **recommended single command** for complete local setup
  - Everything runs automatically except the UI (which must be started separately)
  - After completion, run `task ui-dev` in a new terminal to start the UI

Notes and tips
- If you change ports, ensure both server and worker agree (worker uses `NOETL_API_URL`).
- If a process fails to start, consult the relevant log file in `logs/` (`server-debug.log` or `worker-debug.log`).
- If ports get stuck, use `task kill-port PORT=<port>` or `task debug-kill-all` to clean up.

Troubleshooting
- `uvicorn` not found: Install with one of: `uv add uvicorn` or `uv pip install uvicorn`.
- Permission issues killing ports: You may need elevated permissions depending on your OS and port.
- Virtualenv: Tasks prefer `.venv/bin/python` when present; create it and install dependencies to match your project environment.

Runtime Override Pattern for Credentials
========================================

NoETL test playbooks use templated authentication to work across different environments (Kubernetes vs local development). The playbooks default to `pg_k8s` credentials but can be overridden at runtime using the `--payload` and `--merge` options.

Playbook Structure:
```yaml
workload:
  pg_auth: pg_k8s  # Default for Kubernetes environment
  # other workload variables...

workflow:
  - step: some_postgres_step
    type: postgres
    auth: "{{ workload.pg_auth }}"  # Uses templated value
    command: |
      SELECT * FROM test_table;
```

Runtime Override Examples:
```bash
# Kubernetes environment (uses default pg_k8s)
noetl execute playbook "tests/fixtures/playbooks/save_storage_test/save_simple_test" \
  --host k8s-cluster-host --port 8082

# Local development (override to use pg_local)  
noetl execute playbook "tests/fixtures/playbooks/save_storage_test/save_simple_test" \
  --host localhost --port 8083 \
  --payload '{"pg_auth": "pg_local"}' --merge

# Override multiple workload variables
noetl execute playbook "my_test_playbook" \
  --host localhost --port 8083 \
  --payload '{"pg_auth": "pg_local", "test_mode": "debug"}' --merge
```

Local Testing Workflow:

**Option 1: One-Command Setup (Recommended)**
```bash
# Complete setup (everything except UI)
task noetl-local-full-setup

# In a new terminal, start UI
task ui-dev

# Test execution
task test-execute-local PLAYBOOK=tests/fixtures/playbooks/save_storage_test/save_simple_test
```

**Option 2: Step-by-Step Setup**
```bash
# 1. Setup local test environment (one-time setup)
task local-setup-test

# 2. Start/restart NoETL services (recommended after setup)
task noetl-local-start

# 3. Create database tables (uses pg_local automatically)
task test-create-tables-local

# 4. Execute specific test playbooks (uses pg_local automatically)
task test-execute-local PLAYBOOK=tests/fixtures/playbooks/save_storage_test/save_simple_test

# 5. Start UI for interaction
task ui-dev
```

The `--merge` flag ensures that the payload values are merged into the existing workload rather than replacing it entirely, allowing you to override specific keys while preserving other workload data.
