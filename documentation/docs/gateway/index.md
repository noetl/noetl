---
sidebar_position: 1
title: Gateway Overview
description: NoETL Gateway - API gateway for authentication and GraphQL proxy
---

# NoETL Gateway

The NoETL Gateway is a Rust-based API gateway that provides authentication, authorization, and GraphQL proxy capabilities for the NoETL platform.

:::info Source Code
For development documentation, local setup, and code details, see the [Gateway Crate README](https://github.com/noetl/noetl/blob/master/crates/gateway/README.md).
:::

## Architecture

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

## Key Features

- **Auth0 Integration**: OAuth2/OIDC authentication via Auth0 Universal Login
- **Session Management**: Session tokens managed via NoETL playbooks
- **GraphQL Proxy**: Authenticated access to NoETL's GraphQL API
- **CORS Support**: Configurable cross-origin resource sharing
- **Stateless Design**: No direct database connections

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/graphql` | POST | Execute playbooks (authenticated) |
| `/graphql` | GET | GraphiQL playground |
| `/api/auth/login` | POST | Auth0 token login |
| `/api/auth/validate` | POST | Validate session |
| `/api/auth/check-access` | POST | Check playbook permissions |

## Documentation

| Guide | Description |
|-------|-------------|
| [Deployment Guide](./deployment-guide) | Building, deploying to GKE, static IP setup |
| [Helm Reference](./helm-reference) | Complete Helm chart configuration |
| [Auth0 Setup](./auth0-setup) | Auth0 application and integration |
| [Cloudflare Setup](./cloudflare-setup) | DNS, SSL, caching configuration |

## Quick Start

### Deploy to GKE

```bash
noetl run automation/iap/gcp/deploy_gke_stack.yaml \
  --set project_id=YOUR_PROJECT_ID \
  --set deploy_gateway=true \
  --set create_cluster=false \
  --set deploy_noetl=false
```

### Local Development

```bash
# Run gateway locally
cd crates/gateway
cargo run

# Environment variables
export ROUTER_PORT=8090
export NOETL_BASE_URL=http://localhost:8082
export CORS_ALLOWED_ORIGINS=http://localhost:3000
```

### Test with Port Forward

```bash
# Port forward to deployed gateway
kubectl port-forward -n gateway svc/gateway 8091:80

# Test health
curl http://localhost:8091/health
```

## Related Resources

- **Source Code**: [`crates/gateway/`](https://github.com/noetl/noetl/tree/master/crates/gateway)
- **Helm Chart**: [`automation/helm/gateway/`](https://github.com/noetl/noetl/tree/master/automation/helm/gateway)
- **UI Fixtures**: [`tests/fixtures/gateway_ui/`](https://github.com/noetl/noetl/tree/master/tests/fixtures/gateway_ui)
- **Auth Playbooks**: [`tests/fixtures/playbooks/api_integration/auth0/`](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/api_integration/auth0)
