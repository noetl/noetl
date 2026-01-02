# noetl CLI (v2.1.2)

NoETL Command Line Tool - Rust-based CLI for managing NoETL server, workers, and resources.

## Installation

### Using Task (recommended)

Build and place the binary in the project's `bin/` directory:
```bash
task noetl:local:build
```

Install to `~/.local/bin/`:
```bash
task noetl:local:install
```

### Manual Build

```bash
cargo build --release
```

The binary will be available at `target/release/noetl`.

## Usage

Check version:
```bash
noetl --version
```

### Server Management

Start NoETL server:
```bash
noetl server start
noetl server start --init-db  # Initialize database on startup
```

Stop NoETL server:
```bash
noetl server stop
noetl server stop --force  # Force stop without confirmation
```

### Worker Management

Start NoETL worker:
```bash
noetl worker start
noetl worker start --max-workers 4
noetl worker start --v2  # Use v2 event-driven architecture
noetl worker start --max-workers 8 --v2
```

Stop NoETL worker:
```bash
noetl worker stop  # Interactive selection if multiple workers
noetl worker stop --name my-worker
noetl worker stop --name my-worker --force
```

### Database Management

Initialize database schema:
```bash
noetl db init
```

Validate database schema:
```bash
noetl db validate
```

### Configuration and Contexts

`noetl` supports multiple contexts to manage different server environments.

#### Add a Context
```bash
noetl context add local --server-url http://localhost:8082 --set-current
noetl context add prod --server-url http://noetl-server:8082
```

#### List Contexts
```bash
noetl context list
```

#### Switch Context
```bash
noetl context use prod
```

#### Show Current Context
```bash
noetl context current
```

### CLI Mode

#### Catalog Management

Register a resource (auto-detects kind: Credential or Playbook):
```bash
noetl catalog register tests/fixtures/playbooks/data_transfer/http_to_postgres_transfer/http_to_postgres_transfer.yaml
```

Get resource details:
```bash
noetl catalog get tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres
```

List resources:
```bash
noetl catalog list Playbook --json
```

#### Execution

Execute a playbook:
```bash
noetl execute playbook tests/fixtures/playbooks/regression_test/master_regression_test --json
```

Get execution status:
```bash
noetl execute status 522107710393811426 --json
```

#### Credentials

Get credential details:
```bash
noetl get credential gcs_service_account --include-data
```

#### SQL Query Execution

Execute SQL queries via NoETL Postgres API:

```bash
# Query with table format (default)
noetl query "SELECT * FROM noetl.keychain LIMIT 5"

# Query with specific schema
noetl query "SELECT execution_id, credential_name FROM noetl.keychain WHERE execution_id = 12345" --schema noetl

# Query with JSON output
noetl query "SELECT * FROM noetl.event ORDER BY created_at DESC LIMIT 10" --format json

# Query public schema tables
noetl query "SELECT * FROM users LIMIT 5" --schema public --format table
```

**Output Formats:**
- `table` (default): Formatted ASCII table with borders
- `json`: Pretty-printed JSON output

**Example Output (table format):**
```
┌────────────────────┬────────────────┬──────────────┐
│ execution_id       │ credential_name│ access_count │
├────────────────────┼────────────────┼──────────────┤
│ 507861119290048685 │ openai-api-key │ 0            │
│ 507861119290048686 │ postgres-creds │ 2            │
└────────────────────┴────────────────┴──────────────┘
(2 rows)
```

#### Registering (Legacy/Explicit)

Register a Credential:
```bash
noetl register credential -f tests/fixtures/credentials/pg_k8s.json
```

Register a Playbook:
```bash
noetl register playbook -f tests/fixtures/playbooks/api_integration/auth0/provision_auth_schema.yaml
```

#### Direct Execution/Status/List

Execute a Playbook:
```bash
noetl exec api_integration/auth0/provision_auth_schema
```

Get Execution Status:
```bash
noetl status <execution_id>
```

List Resources:
```bash
noetl list Playbook
```

### Interactive TUI Mode

Run `noetl` with the `-i` or `--interactive` flag:

```bash
noetl --interactive
```

- **Navigation**: Use Up/Down arrows or `j`/`k` to navigate lists.
- **Refresh**: Press `r` to refresh the data.
- **Quit**: Press `q` to exit.

## Docker

```bash
docker build -t noetl .
docker run --rm noetl --help
```
