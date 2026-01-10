# Gateway Kubernetes Deployment

Kubernetes manifests for deploying the NoETL Gateway (Rust API + Static UI) to kind cluster.

## Components

### Gateway API (Rust)
- **Deployment**: `deployment.yaml` - Rust gateway service
- **Service**: `service.yaml` - NodePort on 30090 (localhost:8090)
- **Image**: `noetl-gateway:latest` (built from crates/gateway/Dockerfile)

### Gateway UI (Nginx)
- **Deployment**: `deployment-ui.yaml` - Nginx serving static files
- **Service**: `service-ui.yaml` - NodePort on 30080 (localhost:8080)
- **ConfigMap**: `configmap-ui.yaml` - Nginx configuration
- **ConfigMap**: `configmap-ui-files.yaml` - UI files (HTML/JS/CSS) from tests/fixtures/gateway_ui/
- **Script**: `regenerate-ui-configmap.sh` - Regenerate UI ConfigMap from source files

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Browser: http://localhost:8080/login.html          │
└────────────────┬────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────┐
│  Gateway UI Pod (Nginx)                             │
│  - Namespace: gateway                               │
│  - NodePort: 30080 → localhost:8080                 │
│  - Serves: /mnt/gateway-ui/* (tests/fixtures/)      │
└────────────────┬────────────────────────────────────┘
                 │ JavaScript fetch()
                 ▼
┌─────────────────────────────────────────────────────┐
│  Gateway API Pod (Rust)                             │
│  - Namespace: gateway                               │
│  - NodePort: 30090 → localhost:8090                 │
│  - Endpoints: /graphql, /api/auth/*                 │
└────────────────┬────────────────────────────────────┘
                 │ HTTP to NoETL server
                 ▼
┌─────────────────────────────────────────────────────┐
│  NoETL Server (Python)                              │
│  - Namespace: noetl                                 │
│  - Service: noetl-server.noetl.svc.cluster.local   │
└─────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# Build and deploy everything
task gateway:deploy-all

# Or step by step:
task gateway:build-image    # Build Gateway Docker image
task gateway:deploy         # Deploy Gateway API
task gateway:deploy-ui      # Deploy Gateway UI

# Check status
task gateway:status

# View logs
task gateway:logs
task gateway:logs-ui

# Test endpoints
task gateway:test
```

## Access URLs

- **Gateway API**: http://localhost:8090/graphql
- **Gateway UI**: http://localhost:8080/login.html
- **Health Check**: http://localhost:8080/health

## Port Mappings (kind config)

```yaml
# Gateway API
- containerPort: 30090
  hostPort: 8090
  
# Gateway UI  
- containerPort: 30080
  hostPort: 8080
```

## File Mounting

UI files are stored in a ConfigMap generated from `tests/fixtures/gateway_ui/`:

```bash
# Regenerate ConfigMap after editing UI files
./ci/manifests/gateway/regenerate-ui-configmap.sh

# Apply to cluster
kubectl apply -f ci/manifests/gateway/configmap-ui-files.yaml
kubectl rollout restart deployment/gateway-ui -n gateway
```

**Important:** The ConfigMap is persisted in `configmap-ui-files.yaml` so it survives cluster rebuilds. Always run the regenerate script after editing UI files to keep the manifest in sync.

## Updating UI Files

When you edit files in `tests/fixtures/gateway_ui/`:

1. **Regenerate ConfigMap manifest:**
   ```bash
   ./ci/manifests/gateway/regenerate-ui-configmap.sh
   ```

2. **Apply changes:**
   ```bash
   kubectl apply -f ci/manifests/gateway/configmap-ui-files.yaml
   kubectl rollout restart deployment/gateway-ui -n gateway
   ```

3. **Verify:**
   ```bash
   curl http://localhost:8080/login.html
   ```

The ConfigMap approach ensures UI files are:
- ✅ Version controlled (committed to git)
- ✅ Survive cluster rebuilds
- ✅ Deployed consistently across environments
- ✅ No need for host mounts or volume shares

## Environment Variables

Gateway API deployment:
- `ROUTER_PORT=8090` - Gateway HTTP port
- `NOETL_BASE_URL=http://noetl-server.noetl.svc.cluster.local:8082` - NoETL server URL
- `RUST_LOG=info,gateway=debug` - Logging level

## Development Workflow

**Edit UI files:**
```bash
# Edit tests/fixtures/gateway_ui/*.html, *.js, *.css
# Restart UI pod to reload
task gateway:restart
```

**Edit Gateway code:**
```bash
# Edit crates/gateway/src/**/*.rs
# Rebuild and redeploy
task gateway:redeploy
```

## Troubleshooting

**Gateway not starting:**
```bash
task gateway:logs
# Check NoETL server is running
kubectl get pods -n noetl
```

**UI files not loading:**
```bash
# Check mount
kubectl exec -n gateway deployment/gateway-ui -- ls -la /usr/share/nginx/html
# Restart UI
task gateway:restart
```

**CORS errors:**
- Check `configmap-ui.yaml` has correct CORS headers
- Verify `API_BASE` in `auth.js` points to correct gateway URL

**Port conflicts:**
```bash
# Check ports are free
lsof -i :8080
lsof -i :8090
```

## Cleanup

```bash
# Remove Gateway completely
task gateway:remove
```
