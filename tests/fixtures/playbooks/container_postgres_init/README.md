# Container-Based PostgreSQL Initialization Test

This fixture demonstrates NoETL's `container` tool for executing database initialization tasks in Kubernetes Jobs. It showcases credential passing, file mounting, and result reporting for containerized workloads.

## Overview

The `container_postgres_init` playbook demonstrates:

1. **Kubernetes Job Execution**: Running containerized scripts as Kubernetes Jobs
2. **Credential Injection**: Passing PostgreSQL credentials securely via environment variables
3. **File Mounting**: Loading SQL and shell scripts from workspace into containers
4. **Multi-Step Workflow**: Coordinating multiple container jobs with verification steps
5. **Result Tracking**: Reporting execution status back to NoETL server
6. **Distributed Tracing**: OpenTelemetry-based observability for debugging and performance monitoring

## Observability & Tracing

This playbook includes OpenTelemetry tracing to provide visibility into:
- Container job creation and execution timing
- Script execution performance
- PostgreSQL query latency
- Step-by-step workflow progression
- Error tracking and debugging context

Traces are sent to ClickHouse observability backend and can be viewed via:
- Grafana dashboards
- ClickHouse SQL queries
- AI Toolkit trace viewer (local development)

**Tracing Configuration:**
```yaml
tracing:
  enabled: true
  service_name: container_postgres_init
  otlp_endpoint: http://clickhouse.observability.svc.cluster.local:4318
  sample_rate: 1.0  # Sample 100% of traces
```

## Architecture

```
NoETL Worker → Kubernetes Job → Container (postgres:16-alpine + scripts) → PostgreSQL
                    ↓
               ConfigMap (scripts/SQL files)
                    ↓
               Init Container (download remote files if needed)
                    ↓
               Main Container (execute scripts with credentials)
                    ↓
               Pod Logs → NoETL Event Log
```

## Files

```
container_postgres_init/
├── README.md                       # This file
├── Dockerfile                      # Container image definition
├── container_postgres_init.yaml    # NoETL playbook
├── scripts/
│   ├── init_schema.sh             # Create schema and execution_log table
│   ├── create_tables.sh           # Create business tables
│   └── seed_data.sh               # Populate test data
└── sql/
    ├── create_schema.sql          # Schema verification SQL
    ├── create_tables.sql          # Table DDL (customers, products, orders)
    └── seed_data.sql              # Sample data inserts
```

## Prerequisites

### Quick Setup (Recommended)

Bootstrap complete NoETL environment with one command:

```bash
# From repository root
make bootstrap
# or
noetl run automation/setup/bootstrap.yaml
```

This will:
- Create Kind Kubernetes cluster
- Deploy PostgreSQL
- Deploy NoETL server and workers
- Set up networking and services

**Enable Observability Stack (Optional):**

```bash
# Deploy ClickHouse, Qdrant, and NATS for tracing/observability
noetl run automation/infrastructure/observability.yaml --set action=deploy-all

# Or deploy individually
noetl run automation/infrastructure/clickhouse.yaml --set action=deploy
noetl run automation/infrastructure/qdrant.yaml --set action=deploy
noetl run automation/infrastructure/nats.yaml --set action=deploy

# Check observability services status
noetl run automation/infrastructure/observability.yaml --set action=status
```

Observability components:
- **ClickHouse**: Stores traces, logs, and metrics (port 30123 HTTP, 30900 native)
- **Qdrant**: Vector database for embeddings (port 30633)
- **NATS JetStream**: Event streaming (port 30422)

### Manual Prerequisites

If not using bootstrap, ensure:

1. **Kubernetes Cluster**: Kind or any Kubernetes cluster with NoETL deployed
2. **NoETL Components**: Server and worker running in cluster
3. **PostgreSQL**: Accessible from Kubernetes pods (e.g., `postgres.postgres.svc.cluster.local`)
4. **Credentials Registered**: `pg_k8s` credential with connection details
5. **Docker Registry Access**: For pushing built container image (Kind uses local load)

## Commands Reference

All commands are available via the NoETL CLI:

| Command | Description |
|---------|-------------|
| `noetl run automation/tests/container/full.yaml` | Complete workflow (build -> register -> execute -> verify) |
| `noetl build --target container-test` | Build image and load into Kind cluster |
| `noetl run automation/playbooks/register.yaml --set path=tests/fixtures/playbooks/container_postgres_init` | Register playbook with NoETL server |
| `noetl run tests/fixtures/playbooks/container_postgres_init/container_postgres_init.yaml` | Execute the playbook |
| `noetl run automation/tests/container/verify.yaml` | Verify results in PostgreSQL |
| `noetl run automation/tests/container/cleanup.yaml` | Drop container_test schema |

**Quick Start**: Run `noetl run automation/tests/container/full.yaml` for automated end-to-end testing.

## Environment Variables

The playbook passes these environment variables to container jobs:

| Variable | Example | Description |
|----------|---------|-------------|
| `PGHOST` | `postgres.postgres.svc.cluster.local` | PostgreSQL hostname |
| `PGPORT` | `5432` | PostgreSQL port |
| `PGDATABASE` | `demo_noetl` | Database name |
| `PGUSER` | Injected from secret | Database user |
| `PGPASSWORD` | Injected from secret | Database password |
| `EXECUTION_ID` | From `{{ execution_id }}` | NoETL execution tracking ID |
| `SCHEMA_NAME` | `container_test` | Target schema name |

**Security Note**: Credentials are injected via Jinja2 template `{{ secret.* }}` references and passed as environment variables to the container. Never hardcode credentials in scripts or images.

## Building the Container Image

### Local Build and Push to Kind

```bash
# Build image
cd tests/fixtures/playbooks/container_postgres_init
docker build -t noetl/postgres-container-test:latest .

# Load into Kind cluster
kind load docker-image noetl/postgres-container-test:latest --name noetl

# Verify image is loaded
docker exec noetl-control-plane crictl images | grep postgres-container-test
```

### Build and Push to Remote Registry

```bash
# Build and tag for your registry
docker build -t your-registry.io/noetl/postgres-container-test:latest .

# Push to registry
docker push your-registry.io/noetl/postgres-container-test:latest

# Update playbook workload.image value
# workload:
#   image: your-registry.io/noetl/postgres-container-test:latest
```

## Usage

### Complete Workflow (Automated)

Run the full test workflow with one command:

```bash
# From repository root
noetl run automation/tests/container/full.yaml
```

This executes:
1. Build container image
2. Load into Kind cluster
3. Register playbook
4. Execute playbook
5. Verify results

### Step-by-Step Execution

#### 1. Bootstrap Environment (First Time Only)

```bash
# Complete setup
make bootstrap
# or
noetl run automation/setup/bootstrap.yaml

# Register test credentials
noetl run automation/credentials/register.yaml --set env=k8s
```

#### 2. Build and Load Container Image

```bash
# Using noetl CLI (recommended)
noetl build --target container-test

# Or using build script
cd tests/fixtures/playbooks/container_postgres_init
./build.sh

# Or manually
docker build -t noetl/postgres-container-test:latest tests/fixtures/playbooks/container_postgres_init/
kind load docker-image noetl/postgres-container-test:latest --name noetl
```

#### 3. Register Credentials

Ensure `pg_k8s` credential is registered:

```bash
curl -X POST "http://localhost:8082/api/credentials" \
  -H 'Content-Type: application/json' \
  --data-binary @tests/fixtures/credentials/pg_k8s.json
```

Or use the noetl CLI:

```bash
noetl run automation/credentials/register.yaml --set env=k8s
```

#### 4. Register Playbook

```bash
# Using noetl CLI (recommended)
noetl run automation/playbooks/register.yaml --set path=tests/fixtures/playbooks/container_postgres_init

# Or directly via CLI
noetl register tests/fixtures/playbooks/container_postgres_init/container_postgres_init.yaml \
  --host localhost --port 8082

# Or via script
./tests/fixtures/register_test_playbooks.sh
```

#### 5. Execute Playbook

```bash
# Using noetl CLI (recommended)
noetl run tests/fixtures/playbooks/container_postgres_init/container_postgres_init.yaml

# Or using execute command
noetl execute playbook tests/fixtures/playbooks/container_postgres_init \
  --host localhost --port 8082 \
  --json

# Or via API
curl -X POST "http://localhost:8082/api/playbooks/execute" \
  -H 'Content-Type: application/json' \
  -d '{
    "path": "tests/fixtures/playbooks/container_postgres_init",
    "payload": {}
  }'
```

#### 6. Verify Results

```bash
# Using noetl CLI (recommended)
noetl run automation/tests/container/verify.yaml

# Or manually check PostgreSQL
```bash
# Connect to Postgres pod
kubectl exec -n postgres deployment/postgres -- psql -U demo -d demo_noetl -c "
  SELECT schemaname, tablename 
  FROM pg_tables 
  WHERE schemaname = 'container_test' 
  ORDER BY tablename;
"

# Check data counts
kubectl exec -n postgres deployment/postgres -- psql -U demo -d demo_noetl -c "
  SELECT 'customers' AS table_name, COUNT(*) FROM container_test.customers
  UNION ALL
  SELECT 'products', COUNT(*) FROM container_test.products
  UNION ALL
  SELECT 'orders', COUNT(*) FROM container_test.orders
  UNION ALL
  SELECT 'order_items', COUNT(*) FROM container_test.order_items;
"

# View execution log
kubectl exec -n postgres deployment/postgres -- psql -U demo -d demo_noetl -c "
  SELECT * FROM container_test.execution_log ORDER BY executed_at;
"
```

## Workflow Steps

### Step 1: `verify_postgres_connection`
- **Tool**: `postgres`
- **Purpose**: Verify connectivity before launching container jobs
- **Action**: Execute simple `SELECT version()` query

### Step 2: `run_schema_creation`
- **Tool**: `container`
- **Image**: `noetl/postgres-container-test:latest`
- **Script**: `scripts/init_schema.sh`
- **Purpose**: Create schema and execution tracking table
- **Credentials**: Injected via env vars from secret manager

### Step 3: `run_table_creation`
- **Tool**: `container`
- **Files Mounted**:
  - `sql/create_schema.sql`
  - `sql/create_tables.sql`
- **Script**: `scripts/create_tables.sh`
- **Purpose**: Create business tables (customers, products, orders, order_items)

### Step 4: `seed_test_data`
- **Tool**: `container`
- **Files Mounted**: `sql/seed_data.sql`
- **Script**: `scripts/seed_data.sh`
- **Purpose**: Populate tables with sample data

### Step 5: `verify_data`
- **Tool**: `postgres`
- **Purpose**: Verify schema, tables, and row counts
- **Action**: Query system catalog and count rows

### Step 6: `cleanup_test_data`
- **Tool**: `postgres`
- **Purpose**: Drop test schema (optional cleanup)
- **Action**: `DROP SCHEMA IF EXISTS container_test CASCADE`

## Container Tool Features Demonstrated

### 1. Script Attribute
```yaml
script:
  uri: ./scripts/init_schema.sh
  source:
    type: file
```

### 2. Runtime Files
```yaml
runtime:
  files:
    - uri: ./sql/create_schema.sql
      source:
        type: file
      mountPath: create_schema.sql
```

### 3. Environment Variable Injection
```yaml
env:
  PGHOST: postgres.postgres.svc.cluster.local
  PGUSER: "{{ secret.POSTGRES_USER }}"
  PGPASSWORD: "{{ secret.POSTGRES_PASSWORD }}"
```

### 4. Resource Limits
```yaml
runtime:
  resources:
    limits:
      cpu: "500m"
      memory: 512Mi
    requests:
      cpu: "100m"
      memory: 128Mi
```

### 5. Job Cleanup
```yaml
runtime:
  cleanup: true  # Delete Job and ConfigMap after completion
```

## Testing with NoETL Automation

The container test workflow can be automated using NoETL playbooks:

```bash
# Build container test image and load into Kind
noetl build --target container-test

# Register container_postgres_init playbook
noetl run automation/playbooks/register.yaml --set path=tests/fixtures/playbooks/container_postgres_init

# Execute container_postgres_init playbook
noetl run tests/fixtures/playbooks/container_postgres_init/container_postgres_init.yaml

# Verify container test results
noetl run automation/tests/container/verify.yaml

# Full container test workflow (build, register, execute, verify)
noetl run automation/tests/container/full.yaml
```

## Troubleshooting

### Script Files Not Found in Worker Pods

**Problem**: Container tool execution fails with "Script/file not found" error.

**Root Cause**: The catalog only stores the playbook YAML content, not the referenced script files. When the playbook is registered, scripts like `./scripts/init_schema.sh` are not uploaded to the worker pods.

**Solutions**:

**Option 1: Mount Host Repository (Testing Only)**

For Kind cluster testing, mount the host repository into worker pods:

```bash
# Apply hostPath volume patch
kubectl patch deployment -n noetl noetl-worker --patch '
spec:
  template:
    spec:
      containers:
      - name: worker
        volumeMounts:
        - name: host-repo
          mountPath: /host-repo
          readOnly: true
      volumes:
      - name: host-repo
        hostPath:
          path: /Users/akuksin/projects/noetl/noetl
          type: Directory
'

# Wait for rollout
kubectl rollout status -n noetl deployment/noetl-worker

# Test
noetl run automation/tests/container/full.yaml
```

**Option 2: Use Remote Storage (Production)**

Store scripts in cloud storage and reference them:

```yaml
script:
  uri: gs://my-bucket/scripts/init_schema.sh
  source:
    type: gcs
    auth: gcp_credential
```

**Option 3: Use HTTP Endpoint**

Host scripts on a web server:

```yaml
script:
  uri: init_schema.sh
  source:
    type: http
    endpoint: https://my-company.com/scripts
```

**Option 4: Embed Scripts (Future Enhancement)**

Store script content directly in playbook using base64 encoding (similar to `code_b64` for python tool).

### Viewing Traces

Query traces from ClickHouse:

```bash
# Get recent traces
kubectl exec -n observability deployment/clickhouse -- clickhouse-client -q "
  SELECT 
    Timestamp,
    ServiceName,
    SpanName,
    Duration,
    StatusCode
  FROM observability.traces
  WHERE ServiceName = 'container_postgres_init'
  ORDER BY Timestamp DESC
  LIMIT 20;
"

# Get trace for specific execution
kubectl exec -n observability deployment/clickhouse -- clickhouse-client -q "
  SELECT 
    SpanName,
    Duration,
    StatusCode,
    SpanAttributes['execution_id'] as execution_id
  FROM observability.traces
  WHERE SpanAttributes['execution_id'] = 'YOUR_EXECUTION_ID'
  ORDER BY Timestamp;
"

# View in Grafana
# Open: http://localhost:3000/explore
# Select ClickHouse datasource
# Query: observability.traces table
```

### Image Pull Errors

```bash
# Check if image is in Kind
docker exec -it noetl-cluster-control-plane crictl images | grep postgres-container-test

# Reload image if missing
kind load docker-image noetl/postgres-container-test:latest --name noetl-cluster
```

### Job Failures

```bash
# List jobs
kubectl get jobs -n noetl

# Check job logs
kubectl logs -n noetl job/<job-name>

# Describe job for events
kubectl describe job -n noetl <job-name>
```

### Credential Issues

```bash
# Verify credential is registered
curl http://localhost:8082/api/credentials | jq '.[] | select(.name=="pg_k8s")'

# Test connection from worker pod
kubectl exec -n noetl deployment/noetl-worker -- \
  psql -h postgres.postgres.svc.cluster.local -U demo -d demo_noetl -c "SELECT 1"
```

### ConfigMap Size Limits

If scripts exceed ConfigMap size limits (1MB), use remote file sources:

```yaml
script:
  uri: gs://your-bucket/scripts/large_script.sh
  source:
    type: gcs
    auth: gcp_credential
```

## Best Practices

1. **Credential Security**: Always use `{{ secret.* }}` template references for sensitive data
2. **Idempotency**: Design scripts to be safely re-runnable (DROP IF EXISTS, INSERT ON CONFLICT)
3. **Error Handling**: Use `set -euo pipefail` in bash scripts and `\set ON_ERROR_STOP on` in SQL
4. **Resource Limits**: Set appropriate CPU/memory limits to prevent resource exhaustion
5. **Cleanup**: Enable `cleanup: true` to remove Jobs and ConfigMaps after completion
6. **Logging**: Include execution context (execution_id, timestamps) in logs and database records
7. **Verification Steps**: Always add verification steps after container operations

## Related Documentation

- [Container Tool Documentation](../../../docs/tools/container.md)
- [Script Attribute Design](../../../docs/script_attribute_design.md)
- [Credential Management](../../../docs/credential_refactoring_summary.md)
- [Kubernetes Deployment Guide](../../../docs/kind_kubernetes.md)

## Example Output

Successful execution should show:

```json
{
  "execution_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "success",
  "steps": {
    "verify_postgres_connection": {"status": "success"},
    "run_schema_creation": {"status": "success", "exit_code": 0},
    "run_table_creation": {"status": "success", "exit_code": 0},
    "seed_test_data": {"status": "success", "exit_code": 0},
    "verify_data": {"status": "success", "row_counts": {"customers": 10, "products": 15, "orders": 5}},
    "cleanup_test_data": {"status": "success"}
  }
}
```

## License

Part of the NoETL test fixtures. See project LICENSE file.
