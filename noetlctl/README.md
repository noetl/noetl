# noetlctl (v2.1.2)

NoETL Command Line Tool and Interactive TUI.

## Installation

### Using Task (recommended)

Build and place the binary in the project's `bin/` directory:
```bash
task noetlctl:local:build
```

Install to `~/.local/bin/`:
```bash
task noetlctl:local:install
```

### Manual Build

```bash
cargo build --release
```

The binary will be available at `target/release/noetlctl`.

## Usage

Check version:
```bash
noetlctl --version
```

### Configuration and Contexts

`noetlctl` supports multiple contexts to manage different server environments.

#### Add a Context
```bash
noetlctl context add local --server-url http://localhost:8082 --set-current
noetlctl context add prod --server-url http://noetl-server:8082
```

#### List Contexts
```bash
noetlctl context list
```

#### Switch Context
```bash
noetlctl context use prod
```

#### Show Current Context
```bash
noetlctl context current
```

### CLI Mode

#### Catalog Management

Register a resource (auto-detects kind: Credential or Playbook):
```bash
noetlctl catalog register tests/fixtures/playbooks/data_transfer/http_to_postgres_transfer/http_to_postgres_transfer.yaml
```

Get resource details:
```bash
noetlctl catalog get tests/fixtures/playbooks/data_transfer/http_iterator_save_postgres
```

List resources:
```bash
noetlctl catalog list Playbook --json
```

#### Execution

Execute a playbook:
```bash
noetlctl execute playbook tests/fixtures/playbooks/regression_test/master_regression_test --json
```

Get execution status:
```bash
noetlctl execute status 522107710393811426 --json
```

#### Credentials

Get credential details:
```bash
noetlctl get credential gcs_service_account --include-data
```

#### SQL Query Execution

Execute SQL queries via NoETL Postgres API:

```bash
# Query with table format (default)
noetlctl query "SELECT * FROM noetl.keychain LIMIT 5"

# Query with specific schema
noetlctl query "SELECT execution_id, credential_name FROM noetl.keychain WHERE execution_id = 12345" --schema noetl

# Query with JSON output
noetlctl query "SELECT * FROM noetl.event ORDER BY created_at DESC LIMIT 10" --format json

# Query public schema tables
noetlctl query "SELECT * FROM users LIMIT 5" --schema public --format table
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
noetlctl register credential -f tests/fixtures/credentials/pg_k8s.json
```

Register a Playbook:
```bash
noetlctl register playbook -f tests/fixtures/playbooks/api_integration/auth0/provision_auth_schema.yaml
```

#### Direct Execution/Status/List

Execute a Playbook:
```bash
noetlctl exec api_integration/auth0/provision_auth_schema
```

Get Execution Status:
```bash
noetlctl status <execution_id>
```

List Resources:
```bash
noetlctl list Playbook
```

### Interactive TUI Mode

Run `noetlctl` with the `-i` or `--interactive` flag:

```bash
noetlctl --interactive
```

- **Navigation**: Use Up/Down arrows or `j`/`k` to navigate lists.
- **Refresh**: Press `r` to refresh the data.
- **Quit**: Press `q` to exit.

## Docker

```bash
docker build -t noetlctl .
docker run --rm noetlctl --help
```
