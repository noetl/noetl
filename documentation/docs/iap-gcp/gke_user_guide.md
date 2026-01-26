# NoETL GKE Deployment - User Guide

This guide explains how to connect to your NoETL GKE cluster and access all components.

## Prerequisites

1. **Google Cloud SDK** installed: `brew install google-cloud-sdk`
2. **kubectl** installed: `brew install kubectl`
3. **NoETL CLI** installed: `brew install noetl-io/tap/noetl`
4. **GCP Project Access**: You need access to the GCP project where the cluster is deployed

## 1. Connect to the Cluster

### First-time Setup

```bash
# Authenticate with GCP
gcloud auth login

# Set your project
gcloud config set project <PROJECT_ID>
# Example: gcloud config set project noetl-demo-19700101

# Get cluster credentials (this configures kubectl)
gcloud container clusters get-credentials noetl-cluster --region us-central1 --project <PROJECT_ID>
```

### Verify Connection

```bash
# Check you're connected to the right cluster
kubectl cluster-info

# View all NoETL-related pods
kubectl get pods -A | grep -E "postgres|nats|clickhouse|noetl|gateway"

# View all services
kubectl get svc -A | grep -E "postgres|nats|clickhouse|noetl|gateway"
```

## 2. Access the Gateway (Public API)

The Gateway is exposed as a public LoadBalancer on port 80.

### Get the Gateway IP

```bash
kubectl get svc gateway -n gateway
# Look for EXTERNAL-IP column
```

### Gateway Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `http://<GATEWAY_IP>/health` | GET | Health check |
| `http://<GATEWAY_IP>/graphql` | POST | GraphQL API (requires auth) |
| `http://<GATEWAY_IP>/api/auth/login` | POST | Exchange Auth0 token for session |
| `http://<GATEWAY_IP>/api/auth/validate` | POST | Validate session token |

### Test Gateway Health

```bash
GATEWAY_IP=$(kubectl get svc gateway -n gateway -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
curl http://$GATEWAY_IP/health
# Should return: ok
```

## 3. Access NoETL Server API (Internal)

The NoETL server is internal-only. Use port-forwarding to access it locally.

### Start Port-Forward

```bash
kubectl port-forward -n noetl svc/noetl 8082:8082
```

### Access Points

| URL | Description |
|-----|-------------|
| http://localhost:8082/docs | Swagger UI (API documentation) |
| http://localhost:8082/health | Health check |
| http://localhost:8082/openapi.json | OpenAPI specification |

### Example: Execute a Playbook via API

```bash
curl -X POST http://localhost:8082/api/execute \
  -H "Content-Type: application/json" \
  -d '{
    "playbook_path": "regression_test/hello_world",
    "variables": {}
  }'
```

## 4. Access PostgreSQL

### Option A: Port-Forward (Recommended)

```bash
# Start port-forward
kubectl port-forward -n postgres svc/postgres 5432:5432

# Connect with psql (in another terminal)
psql -h localhost -p 5432 -U postgres -d noetl
# Password: demo
```

### Option B: kubectl exec

```bash
# Get shell access to postgres
kubectl exec -it -n postgres postgres-0 -- psql -U postgres -d noetl

# Run a single query
kubectl exec -n postgres postgres-0 -- psql -U postgres -d noetl -c "SELECT count(*) FROM noetl.event"
```

### Databases Available

| Database | User | Password | Description |
|----------|------|----------|-------------|
| `noetl` | `postgres` | `demo` | Main NoETL database (events, catalog, etc.) |
| `noetl` | `noetl` | `demo` | NoETL application user |
| `demo_noetl` | `demo` | `demo` | Demo/testing database |

### Useful Queries

```sql
-- View recent events
SELECT execution_id, event_type, node_name, created_at
FROM noetl.event
ORDER BY created_at DESC
LIMIT 20;

-- Count events by type
SELECT event_type, count(*) as cnt
FROM noetl.event
GROUP BY event_type
ORDER BY cnt DESC;

-- View registered playbooks
SELECT catalog_id, path, name, created_at
FROM noetl.catalog
ORDER BY created_at DESC;

-- View registered credentials
SELECT name, type, description
FROM noetl.credential;
```

## 5. Access ClickHouse

### Option A: Port-Forward (HTTP Interface)

```bash
# Start port-forward
kubectl port-forward -n clickhouse svc/clickhouse 8123:8123

# Query via HTTP
curl "http://localhost:8123/?query=SELECT%20count()%20FROM%20observability.noetl_events"

# Or use clickhouse-client if installed locally
clickhouse-client --host localhost --port 9000
```

### Option B: kubectl exec

```bash
# Interactive shell
kubectl exec -it -n clickhouse clickhouse-0 -- clickhouse-client

# Run a single query
kubectl exec -n clickhouse clickhouse-0 -- clickhouse-client --query="SELECT count() FROM observability.noetl_events"
```

### Useful Queries

```sql
-- Event count
SELECT count() FROM observability.noetl_events;

-- Events by type
SELECT EventType, count() as cnt
FROM observability.noetl_events
GROUP BY EventType
ORDER BY cnt DESC;

-- Slowest executions
SELECT ExecutionId, count() as events,
       dateDiff('second', min(Timestamp), max(Timestamp)) as duration_sec
FROM observability.noetl_events
GROUP BY ExecutionId
ORDER BY duration_sec DESC
LIMIT 10;

-- Failed events
SELECT ExecutionId, EventType, StepName, ErrorMessage
FROM observability.noetl_events
WHERE EventType LIKE '%failed%' OR EventType LIKE '%error%'
ORDER BY Timestamp DESC
LIMIT 20;
```

## 6. Upload Playbooks

### Option A: Using NoETL CLI (Recommended)

```bash
# Register a playbook
noetl register playbook --file path/to/your_playbook.yaml

# List registered playbooks
noetl list playbooks

# Run a playbook
noetl run your_playbook_name --set key=value
```

### Option B: Using API Directly

```bash
# With port-forward running (kubectl port-forward -n noetl svc/noetl 8082:8082)
curl -X POST http://localhost:8082/api/playbooks \
  -H "Content-Type: application/json" \
  -d @your_playbook.json
```

### Playbook File Structure

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: my_playbook
  path: my_category/my_playbook
  description: "Description of what this playbook does"

executor:
  profile: local  # or 'distributed' for worker execution
  version: noetl-runtime/1

workload:
  # Your variables here
  param1: value1

workflow:
  - step: start
    desc: First step
    tool:
      kind: shell
      cmds:
        - echo "Hello {{ workload.param1 }}"
    next:
      - step: end

  - step: end
    desc: Workflow complete
```

## 7. Upload Credentials

### Create Credential File

```json
{
  "name": "my_credential",
  "type": "postgres",
  "description": "My database connection",
  "tags": ["production", "database"],
  "data": {
    "db_host": "your-host.example.com",
    "db_port": "5432",
    "db_user": "username",
    "db_password": "password",
    "db_name": "database_name"
  }
}
```

### Register Credential

```bash
# Register
noetl register credential --file path/to/credential.json

# List credentials
noetl list credentials
```

### Credential Types

| Type | Required Fields |
|------|-----------------|
| `postgres` | `db_host`, `db_port`, `db_user`, `db_password`, `db_name` |
| `clickhouse` | `ch_host`, `ch_port`, `ch_user`, `ch_password`, `ch_database` |
| `snowflake` | `sf_account`, `sf_user`, `sf_password`, `sf_warehouse`, `sf_database` |
| `http` | `base_url`, `headers` (optional) |
| `api_key` | `api_key`, `base_url` (optional) |

## 8. View Logs

### NoETL Server Logs

```bash
# Recent logs
kubectl logs -n noetl -l app=noetl --tail=100

# Stream logs in real-time
kubectl logs -n noetl -l app=noetl -f
```

### NoETL Worker Logs

```bash
# Recent logs
kubectl logs -n noetl -l app=noetl-worker --tail=100

# Stream logs in real-time
kubectl logs -n noetl -l app=noetl-worker -f
```

### Gateway Logs

```bash
kubectl logs -n gateway -l app=gateway --tail=100 -f
```

### GCP Cloud Logging

```bash
# View all NoETL logs in GCP
gcloud logging read "resource.type=k8s_container AND resource.labels.namespace_name=noetl" \
  --limit=50 \
  --project=<PROJECT_ID>
```

## 9. Common Operations

### Run Post-Deployment Setup

If databases or schemas are missing:

```bash
noetl run automation/iap/gcp/post_deploy_setup.yaml --set action=setup
```

### Sync Events to ClickHouse

```bash
# Manual sync via kubectl
kubectl exec -n postgres postgres-0 -- psql -U postgres -d noetl -t -A -c "
SELECT json_build_object(
  'Timestamp', to_char(created_at, 'YYYY-MM-DD HH24:MI:SS'),
  'EventId', event_id::text,
  'ExecutionId', execution_id::text,
  'EventType', COALESCE(event_type, ''),
  'Status', COALESCE(status, ''),
  'StepName', COALESCE(node_name, ''),
  'Duration', COALESCE((duration * 1000)::bigint, 0),
  'ErrorMessage', COALESCE(error, '')
)
FROM noetl.event
WHERE created_at >= NOW() - INTERVAL '1 hour'
LIMIT 1000;
" | kubectl exec -i -n clickhouse clickhouse-0 -- clickhouse-client --query="INSERT INTO observability.noetl_events FORMAT JSONEachRow"
```

### Restart Components

```bash
# Restart NoETL server
kubectl rollout restart deployment/noetl -n noetl

# Restart workers
kubectl rollout restart deployment/noetl-worker -n noetl

# Restart gateway
kubectl rollout restart deployment/gateway -n gateway
```

### Scale Workers

```bash
# Scale to 3 workers
kubectl scale deployment/noetl-worker -n noetl --replicas=3

# Check status
kubectl get pods -n noetl -l app=noetl-worker
```

## 10. Troubleshooting

### Pod Not Starting

```bash
# Check pod status
kubectl describe pod <POD_NAME> -n <NAMESPACE>

# Check events
kubectl get events -n <NAMESPACE> --sort-by='.lastTimestamp'
```

### Database Connection Issues

```bash
# Test PostgreSQL connectivity from within cluster
kubectl run -it --rm debug --image=postgres:16 --restart=Never -- \
  psql -h postgres.postgres.svc.cluster.local -U postgres -d noetl -c "SELECT 1"
```

### Gateway Not Accessible

```bash
# Check service
kubectl get svc gateway -n gateway -o yaml

# Check if LoadBalancer IP is assigned
kubectl get svc gateway -n gateway -o jsonpath='{.status.loadBalancer.ingress[0].ip}'

# Check firewall rules in GCP Console if IP is assigned but not reachable
```

### Playbook Execution Stuck

```bash
# Check execution status
noetl status <EXECUTION_ID>

# Check worker logs for errors
kubectl logs -n noetl -l app=noetl-worker --tail=200 | grep <EXECUTION_ID>
```

## Quick Reference

### Port-Forward Commands

```bash
# All services at once (run in separate terminals)
kubectl port-forward -n noetl svc/noetl 8082:8082
kubectl port-forward -n postgres svc/postgres 5432:5432
kubectl port-forward -n clickhouse svc/clickhouse 8123:8123
kubectl port-forward -n nats svc/nats 4222:4222
```

### Service URLs (with port-forward)

| Service | Local URL |
|---------|-----------|
| NoETL Server | http://localhost:8082 |
| NoETL Docs | http://localhost:8082/docs |
| PostgreSQL | localhost:5432 |
| ClickHouse HTTP | http://localhost:8123 |
| NATS | localhost:4222 |

### In-Cluster Service DNS

| Service | DNS Name |
|---------|----------|
| NoETL Server | `noetl.noetl.svc.cluster.local:8082` |
| PostgreSQL | `postgres.postgres.svc.cluster.local:5432` |
| ClickHouse | `clickhouse.clickhouse.svc.cluster.local:8123` |
| NATS | `nats.nats.svc.cluster.local:4222` |
| Gateway | `gateway.gateway.svc.cluster.local:80` |
