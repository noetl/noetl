---
sidebar_position: 2
title: Deployment Guide
description: Building and deploying NoETL Gateway to GKE
---

# Gateway Deployment Guide

Complete guide for building and deploying the NoETL Gateway to Google Kubernetes Engine (GKE).

:::tip Development Setup
For local development and running the gateway from source, see the [Gateway Crate README](https://github.com/noetl/noetl/blob/master/crates/gateway/README.md).
:::

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Prerequisites](#prerequisites)
- [Building the Gateway](#building-the-gateway)
- [Deploying to GKE](#deploying-to-gke)
- [Static IP Configuration](#static-ip-configuration)
- [Helm Chart Configuration](#helm-chart-configuration)
- [Cloudflare Setup](#cloudflare-setup)
- [Auth0 Configuration](#auth0-configuration)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)

## Architecture Overview

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Browser   │────▶│  Cloudflare │────▶│   Gateway   │────▶│   NoETL     │
│             │     │   (Proxy)   │     │ (GKE/K8s)   │     │   Server    │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
       │                                       │
       │                                       ▼
       │                              ┌─────────────┐
       └─────────────────────────────▶│    Auth0    │
              (Authentication)        │  (Identity) │
                                      └─────────────┘
```

The Gateway provides:
- **Auth0 Integration**: Handles OAuth2/OIDC authentication via Auth0
- **Session Management**: Creates and validates session tokens via NoETL playbooks
- **CORS Support**: Configurable cross-origin resource sharing
- **GraphQL Proxy**: Proxies authenticated requests to NoETL's GraphQL API

## Current Production Configuration

:::info Working Production Setup (mestumre.dev)
| Setting | Value |
|---------|-------|
| Gateway URL | `https://gateway.mestumre.dev` |
| Static IP | `34.46.180.136` |
| Auth0 Domain | `mestumre-development.us.auth0.com` |
| SSL Mode | Flexible (Cloudflare → HTTP origin) |
| GKE Cluster | `noetl-cluster` (us-central1) |
| Project | `noetl-demo-19700101` |
:::

## Prerequisites

- Google Cloud SDK (`gcloud`) configured with appropriate permissions
- `kubectl` configured to access your GKE cluster
- `helm` v3.x installed
- Auth0 account and application configured
- Cloudflare account (optional, for DNS and CDN)

## Building the Gateway

### Local Build

```bash
# Build in release mode
cargo build --release -p gateway

# Binary location
./target/release/gateway
```

### Cloud Build (Recommended for GKE)

The gateway is built automatically via Google Cloud Build when deploying:

```bash
noetl run automation/iap/gcp/deploy_gke_stack.yaml \
  --set project_id=YOUR_PROJECT_ID \
  --set deploy_gateway=true \
  --set create_cluster=false \
  --set deploy_noetl=false
```

This command:
1. Uploads source code to Cloud Storage
2. Triggers Cloud Build to compile the Rust binary
3. Creates a Docker image and pushes to Artifact Registry
4. Deploys the image to GKE via Helm

### Manual Docker Build

```bash
# Build the Docker image
docker build -f Dockerfile.gateway -t noetl-gateway:latest .

# Tag for Artifact Registry
docker tag noetl-gateway:latest \
  us-central1-docker.pkg.dev/YOUR_PROJECT/noetl/noetl-gateway:latest

# Push to registry
docker push us-central1-docker.pkg.dev/YOUR_PROJECT/noetl/noetl-gateway:latest
```

## Deploying to GKE

### Full Stack Deployment

Deploy the entire NoETL stack including the gateway:

```bash
noetl run automation/iap/gcp/deploy_gke_stack.yaml \
  --set project_id=YOUR_PROJECT_ID \
  --set create_cluster=true \
  --set create_artifact_registry=true \
  --set deploy_postgres=true \
  --set deploy_nats=true \
  --set deploy_clickhouse=true \
  --set deploy_noetl=true \
  --set deploy_gateway=true
```

### Gateway-Only Deployment

Deploy only the gateway (assuming other components exist):

```bash
noetl run automation/iap/gcp/deploy_gke_stack.yaml \
  --set project_id=YOUR_PROJECT_ID \
  --set deploy_gateway=true \
  --set create_cluster=false \
  --set create_artifact_registry=false \
  --set deploy_postgres=false \
  --set deploy_nats=false \
  --set deploy_clickhouse=false \
  --set deploy_noetl=false
```

### Manual Helm Deployment

```bash
# Create namespace
kubectl create namespace gateway

# Deploy with Helm
helm upgrade --install noetl-gateway automation/helm/gateway \
  -n gateway \
  --set image.repository=us-central1-docker.pkg.dev/YOUR_PROJECT/noetl/noetl-gateway \
  --set image.tag=latest
```

### Verify Deployment

```bash
# Check pods
kubectl get pods -n gateway

# Check service
kubectl get svc -n gateway

# View logs
kubectl logs -n gateway deployment/gateway

# Test health endpoint
kubectl port-forward -n gateway svc/gateway 8091:80
curl http://localhost:8091/health
```

## Static IP Configuration

### Reserve a Static IP

```bash
# Reserve a regional static IP
gcloud compute addresses create gateway-static-ip \
  --project=YOUR_PROJECT_ID \
  --region=us-central1 \
  --network-tier=PREMIUM

# Get the reserved IP address
gcloud compute addresses describe gateway-static-ip \
  --project=YOUR_PROJECT_ID \
  --region=us-central1 \
  --format="get(address)"
```

### Configure Helm Values

Update `automation/helm/gateway/values.yaml`:

```yaml
service:
  type: LoadBalancer
  port: 8090
  loadBalancerIP: "YOUR_STATIC_IP"  # e.g., "34.46.180.136"
```

### Apply Changes

```bash
# Delete existing service (required to change IP)
kubectl delete svc gateway -n gateway

# Redeploy with Helm
helm upgrade noetl-gateway automation/helm/gateway -n gateway \
  --set image.repository=us-central1-docker.pkg.dev/YOUR_PROJECT/noetl/noetl-gateway \
  --set image.tag=latest

# Verify static IP is assigned
kubectl get svc -n gateway
```

## Helm Chart Configuration

### values.yaml Reference

```yaml
namespace: gateway

image:
  repository: ""  # Set during deployment
  tag: "latest"
  pullPolicy: IfNotPresent

service:
  type: LoadBalancer        # or ClusterIP for internal only
  port: 8090
  nodePort: null
  loadBalancerIP: ""        # Static IP (optional)

ingress:
  enabled: false            # Enable for GKE Ingress with managed certs
  className: gce
  host: gateway.example.com
  tls:
    enabled: true
  managedCertificate:
    enabled: true
    name: gateway-managed-cert

env:
  routerPort: "8090"
  noetlBaseUrl: "http://noetl.noetl.svc.cluster.local:8082"
  rustLog: "info,gateway=debug"
  corsAllowedOrigins: "http://localhost:8080,http://localhost:8090,https://your-domain.com"
  natsUrl: "nats://nats.nats.svc.cluster.local:4222"
  natsUpdatesSubjectPrefix: "playbooks.executions."

resources:
  requests:
    memory: "128Mi"
    cpu: "100m"
  limits:
    memory: "512Mi"
    cpu: "500m"
```

### Environment Variables

#### Server Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ROUTER_PORT` | Port the gateway listens on | `8090` |
| `NOETL_BASE_URL` | NoETL server URL | `http://noetl.noetl.svc.cluster.local:8082` |
| `RUST_LOG` | Log level configuration | `info,gateway=debug` |
| `CORS_ALLOWED_ORIGINS` | Comma-separated list of allowed origins | `http://localhost:8080` |

#### NATS Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `NATS_URL` | NATS server URL | `nats://nats:4222` |
| `NATS_SESSION_BUCKET` | NATS K/V bucket for session cache | `sessions` |
| `NATS_SESSION_CACHE_TTL_SECS` | Session cache TTL in seconds | `3600` |
| `NATS_REQUEST_BUCKET` | NATS K/V bucket for async requests | `requests` |
| `NATS_REQUEST_TTL_SECS` | Async request TTL in seconds | `1800` |
| `NATS_CALLBACK_SUBJECT_PREFIX` | NATS subject prefix for callbacks | `gateway.callback` |

#### Transport Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `GATEWAY_HEARTBEAT_INTERVAL_SECS` | SSE heartbeat interval | `30` |
| `GATEWAY_CONNECTION_TIMEOUT_SECS` | SSE connection timeout | `300` |

## Cloudflare Setup

### DNS Configuration

1. Log into Cloudflare Dashboard
2. Select your domain
3. Go to **DNS** > **Records**
4. Add an A record:

| Type | Name | Content | Proxy status | TTL |
|------|------|---------|--------------|-----|
| A | gateway | YOUR_STATIC_IP | Proxied | Auto |

### SSL/TLS Settings

1. Go to **SSL/TLS** > **Overview**
2. Set encryption mode to **Full (strict)** if using HTTPS backend
3. Or **Full** if backend uses self-signed certificates

### CORS with Cloudflare

When Cloudflare is proxying requests, CORS headers from your origin server are preserved. However, ensure:

1. Your gateway's `CORS_ALLOWED_ORIGINS` includes your frontend domain
2. Cloudflare's caching doesn't interfere with preflight requests

To disable caching for API endpoints, create a Page Rule:
- URL: `gateway.yourdomain.com/api/*`
- Setting: Cache Level = Bypass

### Firewall Rules (Optional)

Restrict access to specific countries or IP ranges:

1. Go to **Security** > **WAF** > **Custom rules**
2. Create rules to allow/block specific traffic

## Auth0 Configuration

### Create Auth0 Application

1. Log into Auth0 Dashboard
2. Go to **Applications** > **Applications**
3. Click **Create Application**
4. Select **Single Page Application**
5. Name it (e.g., "NoETL Gateway")

### Configure Application Settings

In your Auth0 application settings:

**Allowed Callback URLs:**
```
http://localhost:8090/login.html
https://gateway.yourdomain.com/login.html
```

**Allowed Logout URLs:**
```
http://localhost:8090/login.html
https://gateway.yourdomain.com/login.html
```

**Allowed Web Origins:**
```
http://localhost:8090
https://gateway.yourdomain.com
```

### Get Credentials

Note these values from your Auth0 application:
- **Domain**: `your-tenant.us.auth0.com`
- **Client ID**: `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`

### Configure Gateway UI

Update `tests/fixtures/gateway_ui/config.js`:

```javascript
const isLocalDev = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
const auth0Config = {
  domain: 'your-tenant.us.auth0.com',
  clientId: 'YOUR_CLIENT_ID',
  redirectUri: isLocalDev
    ? 'http://localhost:8090/login.html'
    : window.location.origin + '/login.html'
};
```

### Auth0 Login Playbook

The gateway uses a NoETL playbook for authentication. Ensure the playbook is registered:

```bash
noetl register playbook -f tests/fixtures/playbooks/api_integration/auth0/auth0_login.yaml
```

The playbook:
1. Validates the Auth0 token
2. Upserts user in the database
3. Creates a session token
4. Returns authentication result

## Testing

### Local Testing Setup

1. **Start static file server** (for login.html):
```bash
cd tests/fixtures/gateway_ui
python3 -m http.server 8090
```

2. **Port-forward gateway**:
```bash
kubectl port-forward -n gateway svc/gateway 8091:80
```

3. **Update login.html** to call local gateway:
```javascript
const GATEWAY_API = 'http://localhost:8091';
```

4. **Open browser**: http://localhost:8090/login.html

### Test Auth Endpoint Directly

```bash
# Test health
curl http://localhost:8091/health

# Test login (with valid Auth0 token)
curl -X POST http://localhost:8091/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "auth0_token": "YOUR_AUTH0_ID_TOKEN",
    "auth0_domain": "your-tenant.us.auth0.com"
  }'
```

### Production Testing

After Cloudflare DNS propagates:

```bash
# Test via Cloudflare
curl https://gateway.yourdomain.com/health

# Check CORS headers
curl -I -X OPTIONS https://gateway.yourdomain.com/api/auth/login \
  -H "Origin: https://your-frontend.com" \
  -H "Access-Control-Request-Method: POST"
```

## Troubleshooting

### Common Issues

#### CORS Errors

**Symptom**: Browser shows "No 'Access-Control-Allow-Origin' header"

**Solutions**:
1. Verify `CORS_ALLOWED_ORIGINS` includes your frontend origin
2. Check if Cloudflare is caching preflight responses
3. Use port-forward to test directly against gateway

```bash
kubectl logs -n gateway deployment/gateway | grep -i cors
```

#### "No output from login playbook"

**Symptom**: Gateway returns 500 with this error

**Cause**: Gateway code expects `output` field but NoETL returns `variables.success`

**Solution**: Ensure gateway is deployed with latest code that reads from `variables.success`

#### Auth0 Callback Error

**Symptom**: Auth0 redirects fail

**Solutions**:
1. Verify callback URL is in Auth0 Allowed Callback URLs
2. Check `redirectUri` in config.js matches Auth0 settings
3. Ensure protocol (http/https) matches exactly

#### LoadBalancer IP Not Assigned

**Symptom**: External IP shows `<pending>`

**Solutions**:
1. Check if static IP exists: `gcloud compute addresses list`
2. Verify IP is in same region as cluster
3. Delete and recreate service after changing `loadBalancerIP`

### Viewing Logs

```bash
# Gateway logs
kubectl logs -n gateway deployment/gateway -f

# NoETL logs (for playbook execution)
kubectl logs -n noetl deployment/noetl -f

# Check events
kubectl get events -n gateway --sort-by=.lastTimestamp
```

### Restarting Gateway

```bash
kubectl rollout restart deployment/gateway -n gateway
kubectl rollout status deployment/gateway -n gateway
```

## Gateway UI Management

The Gateway UI is served via Kubernetes ConfigMaps. When you modify files in `tests/fixtures/gateway_ui/`, you need to update the deployed ConfigMap.

### Update UI Files

After modifying any UI files (HTML, JS, CSS):

```bash
# Update UI ConfigMap and restart deployment
noetl run automation/infrastructure/gateway-ui.yaml --set action=update
```

This command:
1. Regenerates the ConfigMap from `tests/fixtures/gateway_ui/`
2. Applies the updated ConfigMap to Kubernetes
3. Restarts the gateway-ui deployment
4. Waits for rollout to complete

### Manual Update

```bash
# Regenerate ConfigMap
./ci/manifests/gateway/regenerate-ui-configmap.sh

# Apply to Kubernetes
kubectl apply -f ci/manifests/gateway/configmap-ui-files.yaml

# Restart deployment to pick up changes
kubectl rollout restart deployment/gateway-ui -n gateway
kubectl rollout status deployment/gateway-ui -n gateway --timeout=30s
```

### Check UI Status

```bash
noetl run automation/infrastructure/gateway-ui.yaml --set action=status
```

### View UI Logs

```bash
noetl run automation/infrastructure/gateway-ui.yaml --set action=logs
```

### Browser Cache

After updating the UI, you may need to hard-refresh your browser:
- **Mac**: Cmd+Shift+R
- **Windows/Linux**: Ctrl+Shift+R

Or clear browser cache completely to ensure you're seeing the latest version.

### UI File Locations

| File | Purpose |
|------|---------|
| `tests/fixtures/gateway_ui/index.html` | Cybx AI Chat interface |
| `tests/fixtures/gateway_ui/dashboard.html` | Admin dashboard (users, playbooks, executions) |
| `tests/fixtures/gateway_ui/login.html` | Auth0 login page |
| `tests/fixtures/gateway_ui/auth.js` | Authentication utilities |
| `tests/fixtures/gateway_ui/config.js` | Auth0 configuration |
| `tests/fixtures/gateway_ui/app.js` | Chat application logic |
| `tests/fixtures/gateway_ui/styles.css` | Shared styles |

## Next Steps

Once the gateway is deployed and working:

1. **Configure Auth0** - See [Auth0 Setup](./auth0-setup) for detailed Auth0 configuration
2. **Set up Cloudflare** - See [Cloudflare Setup](./cloudflare-setup) for DNS and SSL configuration
3. **Use the API** - See [API Usage Guide](./api-usage) for how to authenticate and call playbooks
