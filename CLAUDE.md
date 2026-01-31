# NoETL Project Instructions

## Automation Commands

**Always use the `noetl` binary** for running automation tasks. Do not use `task` or other task runners.

### Common Commands

```bash
# Execute a playbook
noetl exec <playbook_path> [--var key=value]

# Check execution status
noetl status <execution_id>
noetl status <execution_id> --json

# Cancel a running execution
noetl cancel <execution_id>
noetl cancel <execution_id> --reason "reason"

# List resources
noetl list Playbook
noetl list Credential --json

# Catalog management
noetl catalog list
noetl catalog list --kind Playbook

# Server management
noetl server start
noetl server start --init-db
noetl server stop

# Worker management
noetl worker start
noetl worker start --max-workers 4
noetl worker stop

# Database operations
noetl db init
noetl db validate

# Execute SQL queries
noetl query "SELECT * FROM noetl.keychain LIMIT 5"

# Kubernetes deployment
noetl k8s deploy
noetl k8s redeploy
noetl k8s reset
noetl k8s remove

# Build Docker images
noetl build
noetl build --no-cache
```

### Connection Options

```bash
# Specify custom host/port
noetl --host=localhost --port=8082 status <execution_id>
```

## Kind Cluster Port Mappings

Port forwarding is configured in `ci/kind/config.yaml`. Do **NOT** use kubectl port-forward - the ports are already mapped to localhost via Kind extraPortMappings.

| Service          | Host Port | Container Port | URL                               |
|------------------|-----------|----------------|-----------------------------------|
| NoETL Server     | 8082      | 30082          | http://localhost:8082             |
| Gateway API      | 8090      | 30090          | http://localhost:8090             |
| Gateway UI       | 8080      | 30080          | http://localhost:8080             |
| PostgreSQL       | 54321     | 30321          | localhost:54321                   |
| Grafana          | 3000      | 30300          | http://localhost:3000             |
| VictoriaLogs     | 9428      | 30428          | http://localhost:9428             |
| NATS Client      | 30422     | 30422          | nats://localhost:30422            |
| NATS Monitoring  | 30822     | 30822          | http://localhost:30822            |
| ClickHouse HTTP  | 30123     | 30123          | http://localhost:30123            |
| Qdrant HTTP      | 30633     | 30633          | http://localhost:30633            |
| Test Server      | 30555     | 30555          | http://localhost:30555            |

## Project Structure

- `crates/` - Rust components (gateway, server, executor, etc.)
- `noetl/` - Python package
- `tests/fixtures/playbooks/` - Playbook definitions
- `automation/` - Automation scripts and configurations
- `documentation/` - Project documentation
- `ci/kind/config.yaml` - Kind cluster configuration with port mappings
