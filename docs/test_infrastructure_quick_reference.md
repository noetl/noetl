# Test Infrastructure Quick Reference

## Pagination Test Server

### Quick Commands

```bash
# Deploy everything
task pagination-server:test:pagination-server:full

# Check status
task pagination-server:test:pagination-server:status

# Test endpoints
task pagination-server:test:pagination-server:test

# View logs
task pagination-server:test:pagination-server:logs

# Remove server
task pagination-server:test:pagination-server:undeploy
```

### Access Points

- **Internal (from within cluster)**: `http://paginated-api.test-server.svc.cluster.local:5555`
- **External (from host)**: `http://localhost:30555`

### Health Check

```bash
# From host
curl http://localhost:30555/health

# From within cluster
kubectl run -n test-server curl-test --image=curlimages/curl:latest --rm -i --restart=Never -- \
  curl -s http://paginated-api:5555/health
```

### Test Endpoints

```bash
# Page-based pagination
curl "http://localhost:30555/api/v1/assessments?page=1"

# Offset-based pagination
curl "http://localhost:30555/api/v1/users?offset=0&limit=5"

# Cursor-based pagination
curl "http://localhost:30555/api/v1/events?cursor=start"

# Flaky endpoint (for retry testing)
curl "http://localhost:30555/api/v1/flaky?page=1"
```

## Regression Testing

### Setup and Run

```bash
# Full setup and run
task test:regression:full

# Individual steps
task test:regression:setup      # Create schema
task test:regression:run        # Execute tests
task test:regression:results    # View results
```

### Register Credentials and Playbooks

```bash
# Register test credentials
task test:k8s:register-credentials

# Register test playbooks
task test:k8s:register-playbooks
```

### Check Test Results

```bash
# View latest results in database
curl -s -X POST "http://localhost:8082/api/postgres/execute" \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT * FROM noetl_test.regression_summary ORDER BY created_at DESC LIMIT 1", "schema": "noetl"}' \
  | jq '.result'
```

## Architecture Verification

### Check Worker is Using HTTP API

```bash
# Check worker logs for HTTP calls (should see POST to /catalog/resource)
kubectl logs -n noetl -l app=noetl-worker --tail=50 | grep catalog

# Should see lines like:
# POST http://noetl.noetl.svc.cluster.local:8080/catalog/resource
```

### Verify Server-Worker Separation

```bash
# Worker should NEVER access noetl schema directly
# Check worker code - should only use HTTP API
grep -r "get_catalog_service" noetl/worker/
# Should return: (no results)

grep -r "catalog/resource" noetl/plugin/
# Should return: HTTP POST calls
```

## Cluster Management

### Recreate Cluster (with new port mappings)

```bash
# Destroy and bootstrap
make destroy && make bootstrap

# Or using tasks
task kind:local:cluster-delete
task kind:local:cluster-create
task bring-all
```

### Check Cluster Health

```bash
task test:k8s:cluster-health
```

## Component Status

### Check All Services

```bash
# NoETL components
kubectl get pods -n noetl

# PostgreSQL
kubectl get pods -n postgres

# Test server
kubectl get pods -n test-server

# Observability
kubectl get pods -n clickhouse
kubectl get pods -n qdrant
kubectl get pods -n nats
```

### Service Endpoints

```bash
# NoETL API
curl http://localhost:8082/health

# Test Server
curl http://localhost:30555/health

# ClickHouse
curl http://localhost:30123/
```

## Troubleshooting

### Test Server Not Starting

```bash
# Check pod status
kubectl get pods -n test-server

# Check pod logs
kubectl logs -n test-server -l app=paginated-api

# Check events
kubectl get events -n test-server --sort-by='.lastTimestamp'

# Restart deployment
kubectl rollout restart deployment/paginated-api -n test-server
```

### Port Not Accessible

```bash
# Check if port mapping exists in kind config
grep "30555" ci/kind/config.yaml

# If not, cluster needs to be recreated
make destroy && make bootstrap

# Verify port mapping
kubectl get svc -n test-server paginated-api-ext -o jsonpath='{.spec.ports[0].nodePort}'
```

### Tests Failing

```bash
# Check specific execution
curl -s "http://localhost:8082/api/execution/{execution_id}" | jq

# Check event log
curl -s -X POST "http://localhost:8082/api/postgres/execute" \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"SELECT * FROM noetl.event WHERE execution_id = {execution_id} ORDER BY event_id DESC LIMIT 10\", \"schema\": \"noetl\"}" \
  | jq '.result'

# Check worker logs
kubectl logs -n noetl -l app=noetl-worker --tail=100
```

## File Locations

### Test Server
- Source: `tests/fixtures/servers/paginated_api.py`
- Dockerfile: `docker/test-server/Dockerfile`
- Manifests: `ci/manifests/test-server/`
- Tasks: `ci/taskfile/test-server.yml`

### Configuration
- Kind config: `ci/kind/config.yaml`
- Main taskfile: `taskfile.yml`

### Documentation
- Deployment summary: `docs/test_server_deployment.md`
- Test results: `docs/regression_test_results_2025_12_03.md`
- Regression testing guide: `documentation/docs/regression-testing.md`
- Copilot instructions: `.github/copilot-instructions.md`

## Common Workflows

### Deploy New NoETL Version

```bash
# Build and deploy
task docker:local:build
task kind:local:image-load
task noetl:k8s:redeploy

# Wait for pods to be ready
kubectl wait --for=condition=ready pod -l app=noetl-server -n noetl --timeout=60s
kubectl wait --for=condition=ready pod -l app=noetl-worker -n noetl --timeout=60s
```

### Run Specific Test

```bash
# Register playbook if needed
noetl register tests/fixtures/playbooks/{test-name}.yaml --host localhost --port 8082

# Execute test
noetl execute playbook {catalog-path} --host localhost --port 8082 --payload '{"pg_auth": "pg_k8s"}' --merge
```

### Clean Up Everything

```bash
# Clear all caches
task clear-all

# Destroy cluster
make destroy

# Start fresh
make bootstrap
```

## Performance Tips

- Use `task *:full` commands for complete workflows
- Run tests in parallel when possible
- Monitor worker logs during test runs
- Check database connections before running tests
- Use ClusterIP for internal communication (faster)
- Use NodePort only for external debugging

## Security Notes

- Test server is internal-only (ClusterIP) by default
- NodePort (30555) is localhost-only (127.0.0.1)
- Test credentials are for development only
- Production deployments should use proper secrets management
