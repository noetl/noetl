# NoETL Kubernetes Environment Variables Checklist

This document lists all required environment variables for NoETL components to function correctly in a Kubernetes cluster.

## Component Connectivity Matrix

| From → To | Service URL | Required For |
|-----------|-------------|--------------|
| Gateway → NoETL Server | `http://noetl.noetl.svc.cluster.local:8082` | Auth playbook execution, API calls |
| Worker → NoETL Server | `http://noetl.noetl.svc.cluster.local:8082` | Event emission, command fetching |
| Worker → Gateway | `http://gateway.gateway.svc.cluster.local:8090` | Callbacks (when executed via UI) |
| Server → NATS | `nats://nats.nats.svc.cluster.local:4222` | Command publishing |
| Worker → NATS | `nats://nats.nats.svc.cluster.local:4222` | Command subscription |
| Gateway → NATS | `nats://nats.nats.svc.cluster.local:4222` | Execution updates |
| Server → Postgres | `postgres.postgres.svc.cluster.local:5432` | Event storage, catalog |
| Worker → Postgres | Via credentials API | Playbook data operations |

---

## 1. NoETL Server (`noetl-server`)

### Required Environment Variables

```yaml
# Core Settings
NOETL_RUN_MODE: "server"
NOETL_HOST: "0.0.0.0"
NOETL_PORT: "8082"
NOETL_SERVER_URL: "http://noetl.noetl.svc.cluster.local:8082"

# PostgreSQL (Internal Database)
POSTGRES_HOST: "postgres.postgres.svc.cluster.local"
POSTGRES_PORT: "5432"
NOETL_POSTGRES_DB: "noetl"
NOETL_SCHEMA: "noetl"
POSTGRES_PASSWORD: "<from secret>"  # Required in noetl-secret

# NATS JetStream
NATS_URL: "nats://noetl:noetl@nats.nats.svc.cluster.local:4222"
NATS_USER: "noetl"
NATS_PASSWORD: "noetl"
NATS_STREAM: "NOETL_COMMANDS"
NATS_SUBJECT: "noetl.commands"
NATS_CONSUMER: "noetl_worker_pool"

# Optional but Recommended
NOETL_DEBUG: "true"
LOG_LEVEL: "INFO"
NOETL_ENABLE_UI: "true"
PYTHONPATH: "/opt/noetl"
TZ: "UTC"
```

### ConfigMap: `noetl-server-config`
### Secret: `noetl-secret` (must contain `POSTGRES_PASSWORD`)

---

## 2. NoETL Worker (`noetl-worker`)

### Required Environment Variables

```yaml
# Core Settings
NOETL_RUN_MODE: "worker"
NOETL_SERVER_URL: "http://noetl.noetl.svc.cluster.local:8082"

# NATS JetStream
NATS_URL: "nats://noetl:noetl@nats.nats.svc.cluster.local:4222"
NATS_USER: "noetl"
NATS_PASSWORD: "noetl"
NATS_STREAM: "NOETL_COMMANDS"
NATS_SUBJECT: "noetl.commands"
NATS_CONSUMER: "noetl_worker_pool"

# Storage Tiers (for result externalization)
NOETL_DEFAULT_STORAGE_TIER: "kv"
NOETL_GCS_BUCKET: "<bucket-name>"      # If using GCS
NOETL_GCS_PREFIX: "results/"
NOETL_S3_BUCKET: "<bucket-name>"       # If using S3
NOETL_S3_REGION: "us-east-1"

# Optional but Recommended
NOETL_DEBUG: "true"
LOG_LEVEL: "DEBUG"
NOETL_DATA_DIR: "/opt/noetl/data"
PYTHONPATH: "/opt/noetl"
TZ: "UTC"
```

### ConfigMap: `noetl-worker-config`
### Note: Worker does NOT need direct Postgres access - it uses Server API for credentials

---

## 3. Gateway (`gateway`)

### Required Environment Variables

```yaml
# Core Settings
ROUTER_PORT: "8090"
RUST_LOG: "info,gateway=debug"

# NoETL Server Connection
NOETL_BASE_URL: "http://noetl.noetl.svc.cluster.local:8082"

# NATS JetStream
NATS_URL: "nats://noetl:noetl@nats.nats.svc.cluster.local:4222"
NATS_UPDATES_SUBJECT_PREFIX: "playbooks.executions."
NATS_CALLBACK_SUBJECT_PREFIX: "noetl.callbacks"

# Auth Playbooks
AUTH_PLAYBOOK_LOGIN: "api_integration/auth0/auth0_login"
AUTH_PLAYBOOK_VALIDATE_SESSION: "api_integration/auth0/auth0_validate_session"
AUTH_PLAYBOOK_CHECK_ACCESS: "api_integration/auth0/check_playbook_access"
AUTH_PLAYBOOK_TIMEOUT_SECS: "60"

# CORS
CORS_ALLOWED_ORIGINS: "http://localhost:8080,http://localhost:8090,http://localhost:3000"
```

---

## 4. Required Kubernetes Resources

### Namespaces
- `noetl` - Server and workers
- `gateway` - Gateway service
- `nats` - NATS JetStream
- `postgres` - PostgreSQL

### Services
```yaml
# NoETL Server Service
apiVersion: v1
kind: Service
metadata:
  name: noetl
  namespace: noetl
spec:
  ports:
  - port: 8082
    targetPort: 8082
  selector:
    app: noetl-server

# Gateway Service
apiVersion: v1
kind: Service
metadata:
  name: gateway
  namespace: gateway
spec:
  ports:
  - port: 8090
    targetPort: 8090
  selector:
    app: gateway
```

### Secrets
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: noetl-secret
  namespace: noetl
type: Opaque
data:
  POSTGRES_PASSWORD: <base64-encoded>
  NOETL_PASSWORD: <base64-encoded>
```

---

## 5. Credential Registration

The following credentials must be registered in the NoETL catalog for auth playbooks:

### PostgreSQL Credential (`pg_auth`)
```bash
noetl credential create --name pg_auth --type postgres --data '{
  "db_host": "postgres.postgres.svc.cluster.local",
  "db_port": "5432",
  "db_user": "noetl",
  "db_password": "<password>",
  "db_name": "noetl"
}'
```

### NATS Credential (`nats_credential`)
```bash
noetl credential create --name nats_credential --type nats --data '{
  "nats_url": "nats://noetl:noetl@nats.nats.svc.cluster.local:4222",
  "nats_user": "noetl",
  "nats_password": "noetl"
}'
```

---

## 6. Auth Playbook Registration

All auth playbooks must be registered in the catalog:

```bash
noetl catalog register tests/fixtures/playbooks/api_integration/auth0/auth0_login.yaml
noetl catalog register tests/fixtures/playbooks/api_integration/auth0/auth0_validate_session.yaml
noetl catalog register tests/fixtures/playbooks/api_integration/auth0/check_playbook_access.yaml
```

---

## 7. Verification Commands

### Check Connectivity
```bash
# Gateway → Server
kubectl exec -n gateway deployment/gateway -- wget -q -O- http://noetl.noetl.svc.cluster.local:8082/api/health

# Worker → Server
kubectl exec -n noetl deployment/noetl-worker -- curl -s http://noetl.noetl.svc.cluster.local:8082/api/health

# Worker → Gateway
kubectl exec -n noetl deployment/noetl-worker -- curl -s http://gateway.gateway.svc.cluster.local:8090/health
```

### Check NATS
```bash
kubectl exec -n nats deployment/nats -- nats stream info NOETL_COMMANDS
```

### Check Credentials
```bash
noetl list Credential
```

### Check Auth Playbooks
```bash
noetl catalog list --kind Playbook | grep auth0
```

---

## 8. Common Issues

### "Callback for unknown request_id"
**Cause**: Playbook executed via CLI, not through Gateway UI
**Resolution**: This is expected. Callbacks only work when execution is initiated through the Gateway UI.

### "Postgres connection is not configured"
**Cause**: Missing `pg_auth` credential or workload variable not resolved
**Resolution**:
1. Register `pg_auth` credential
2. Ensure playbook uses `auth: "{{ workload.pg_auth }}"` (not circular reference)

### "You do not have permission to execute this playbook"
**Cause**: Auth playbooks not registered or permission check failing
**Resolution**:
1. Register all auth0 playbooks
2. Check `auth.playbook_permissions` table has correct entries
3. Verify user has active session in `auth.sessions`

### Gateway not receiving auth callbacks
**Cause**: Playbooks using wrong `gateway_url`
**Resolution**: Ensure `gateway_url: "http://gateway.gateway.svc.cluster.local:8090"` in playbook workload
