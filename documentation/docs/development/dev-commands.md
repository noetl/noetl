# Kind Development Commands Reference

Quick reference for common development tasks in the Kind cluster.

## Hot-Reload Python Code

### Initial Setup (One-time)

```bash
# Create ConfigMap with the Python file
kubectl create configmap noetl-v2-patch -n noetl \
  --from-file=v2.py=noetl/server/api/v2.py

# Patch noetl-server deployment
kubectl patch deployment noetl-server -n noetl --type='json' -p='[
  {"op": "add", "path": "/spec/template/spec/volumes/-", "value": {"name": "v2-patch", "configMap": {"name": "noetl-v2-patch"}}},
  {"op": "add", "path": "/spec/template/spec/containers/0/volumeMounts/-", "value": {"name": "v2-patch", "mountPath": "/opt/noetl/noetl/server/api/v2.py", "subPath": "v2.py"}}
]'

# Patch noetl-worker deployment
kubectl patch deployment noetl-worker -n noetl --type='json' -p='[
  {"op": "add", "path": "/spec/template/spec/volumes/-", "value": {"name": "v2-patch", "configMap": {"name": "noetl-v2-patch"}}},
  {"op": "add", "path": "/spec/template/spec/containers/0/volumeMounts/-", "value": {"name": "v2-patch", "mountPath": "/opt/noetl/noetl/server/api/v2.py", "subPath": "v2.py"}}
]'
```

### Apply Code Changes

```bash
# Update ConfigMap
kubectl create configmap noetl-v2-patch -n noetl \
  --from-file=v2.py=noetl/server/api/v2.py \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart deployments
kubectl rollout restart deployment/noetl-server deployment/noetl-worker -n noetl
kubectl rollout status deployment/noetl-server deployment/noetl-worker -n noetl
```

## Update Gateway UI

```bash
kubectl create configmap gateway-ui-files -n gateway \
  --from-file=tests/fixtures/gateway_ui/index.html \
  --from-file=tests/fixtures/gateway_ui/login.html \
  --from-file=tests/fixtures/gateway_ui/styles.css \
  --from-file=tests/fixtures/gateway_ui/app.js \
  --from-file=tests/fixtures/gateway_ui/auth.js \
  --from-file=tests/fixtures/gateway_ui/env.js \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl rollout restart deployment/gateway-ui -n gateway
```

## Update Gateway (Rust)

```bash
docker build -t noetl/gateway:dev -f crates/gateway/Dockerfile .
kind load docker-image noetl/gateway:dev --name noetl
kubectl rollout restart deployment/gateway -n gateway
```

## Register Playbook

```bash
python3 << 'EOF'
import json
with open('tests/fixtures/playbooks/api_integration/amadeus_ai_api/amadeus_ai_api.yaml', 'r') as f:
    content = f.read()
payload = {"path": "api_integration/amadeus_ai_api", "kind": "Playbook", "content": content}
with open('/tmp/playbook.json', 'w') as f:
    json.dump(payload, f)
EOF

curl -X POST http://localhost:8082/api/catalog/register \
  -H "Content-Type: application/json" \
  -d @/tmp/playbook.json
```

## Debugging

```bash
# Pod status
kubectl get pods -n noetl
kubectl get pods -n gateway

# Logs
kubectl logs -n noetl -l app=noetl-server --tail=100
kubectl logs -n noetl -l app=noetl-worker --tail=100
kubectl logs -n gateway -l app=gateway --tail=100

# Query execution events
kubectl exec -n postgres deploy/postgres -- psql -U noetl -d noetl -c "
  SELECT event_type, node_name, status, created_at
  FROM noetl.event
  WHERE execution_id = <EXECUTION_ID>
  ORDER BY created_at DESC
  LIMIT 20
"

# Verify ConfigMap
kubectl get configmap noetl-v2-patch -n noetl -o jsonpath='{.data.v2\.py}' | head -50

# Check mounted file
kubectl exec -n noetl deploy/noetl-server -- head -50 /opt/noetl/noetl/server/api/v2.py
```
