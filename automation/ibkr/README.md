# IBKR Client Portal Gateway Integration

NoETL integration with Interactive Brokers Client Portal Gateway for automated trading operations.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         NoETL Server/Worker Playbooks                       │
│       tests/fixtures/playbooks/interactive_brokers/ibkr_api.yaml            │
│       - TOTP generation via Python tool (pyotp)                             │
│       - HTTP calls to IBKR Client Portal Gateway                            │
│       - Credential management via NoETL keychain                            │
└─────────────────────────────┬───────────────────────────────────────────────┘
                              │ HTTPS (self-signed cert, verify_ssl: false)
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                 IBKR Client Portal Gateway (Kubernetes)                     │
│                 https://localhost:30500 (NodePort)                          │
│                 https://ibkr-client-portal.ibkr.svc:5000 (internal)         │
│                                                                             │
│       Official IBKR Java gateway for REST API access                        │
│       Built via: noetl run automation/ibkr/build.yaml                       │
│       Deployed via: noetl run automation/ibkr/deploy.yaml                   │
│       All-in-one: noetl run automation/ibkr/setup_full.yaml                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Option 1: All-in-One Setup

```bash
# Build and deploy IBKR gateway in one command
noetl run automation/ibkr/setup_full.yaml

# Gateway will be available at:
# - External: https://localhost:30500
# - Internal: https://ibkr-client-portal.ibkr.svc.cluster.local:5000
```

### Option 2: Step-by-Step

```bash
# 1. Build Docker image (downloads official IBKR Client Portal Gateway)
noetl run automation/ibkr/build.yaml

# 2. Deploy to Kubernetes
noetl run automation/ibkr/deploy.yaml

# 3. Verify deployment
kubectl -n ibkr get pods
kubectl -n ibkr get svc
```

### Login to IBKR Gateway

```bash
# Open browser to login (accept self-signed cert warning)
open https://localhost:30500

# Login with IBKR credentials in browser
# After login, API calls work via server/worker playbooks
```

## Playbooks

### Build and Deploy (Local Shell)

**`automation/ibkr/build.yaml`** - Build IBKR gateway Docker image

Downloads official IBKR Client Portal Gateway and builds/loads image:

```bash
noetl run automation/ibkr/build.yaml
```

Steps:
1. Creates `docker/ibkr-gateway/` directory
2. Downloads gateway from `download2.interactivebrokers.com/portal/clientportal.gw.zip`
3. Builds Docker image `ibkr-client-portal:latest`
4. Loads image to kind cluster

**`automation/ibkr/deploy.yaml`** - Deploy gateway to Kubernetes

```bash
noetl run automation/ibkr/deploy.yaml
```

Steps:
1. Creates `ibkr` namespace
2. Applies manifests from `ci/manifests/ibkr-gateway/`
3. Waits for deployment rollout
4. Shows status

**`automation/ibkr/setup_full.yaml`** - Build and deploy in one command

```bash
noetl run automation/ibkr/setup_full.yaml
```

Combines build.yaml and deploy.yaml for complete setup.

### API Operations (Server/Worker Mode)

**Prerequisites**: Playbooks must be registered in the catalog before distributed execution.

Located at `tests/fixtures/playbooks/interactive_brokers/ibkr_api.yaml`:

```bash
# Step 1: Register the playbook in catalog (one time)
noetl register playbook --file tests/fixtures/playbooks/interactive_brokers/ibkr_api.yaml
# Returns: {"path":"automation/ibkr/api", ...}

# Step 2: Execute on server/worker using the catalog path (automation/ibkr/api)
# Check auth status
noetl run automation/ibkr/api -r distributed --set action=status

# Keep session alive (call every ~55 seconds)
noetl run automation/ibkr/api -r distributed --set action=tickle

# Get accounts
noetl run automation/ibkr/api -r distributed --set action=accounts

# Get positions/orders (similar pattern)
```

**Alternative - Local Execution** (no registration needed):
```bash
# Execute locally using file path - supports direct --set parameters
noetl run tests/fixtures/playbooks/interactive_brokers/ibkr_api.yaml --set action=status
noetl run tests/fixtures/playbooks/interactive_brokers/ibkr_api.yaml --set action=accounts
```

**Note**: 
- Registration uses the playbook's `metadata.path` (automation/ibkr/api), NOT the file path
- **Distributed execution**: `noetl run <catalog_path> -r distributed --set key=value`
- **Local execution**: `noetl run <file_path> --set key=value`
- Reference type (file vs catalog) is auto-detected by path pattern

### Verify Gateway (Server/Worker)

Distributed verify playbook: `automation/ibkr/verify` (file: `tests/fixtures/playbooks/interactive_brokers/ibkr_gateway_verify.yaml`).

```bash
noetl run automation/ibkr/verify -r distributed --set credential=ib_gateway
```

### Verify Gateway (Local Execution)

Local verify playbook file: `automation/ibkr/verify.yaml` (metadata path `automation/ibkr/verify-local`).

```bash
noetl run automation/ibkr/verify.yaml --set gateway_url=https://localhost:30500
```

## Network Access

| Access Method | URL | Notes |
|---------------|-----|-------|
| NodePort (external) | `https://localhost:15000` | Mapped via kind config (30500->15000) |
| ClusterIP (internal) | `https://ibkr-client-portal.ibkr.svc.cluster.local:5000` | For NoETL workers |

## File Structure

```
automation/ibkr/
├── README.md                    # This file
├── build.yaml                   # Build Docker image (local shell)
└── deploy.yaml                  # Deploy to K8s (local shell)

ci/manifests/ibkr-gateway/
├── deployment.yaml              # K8s Deployment
└── service.yaml                 # K8s Service (NodePort 30500)

ci/kind/config.yaml              # Port mapping: 30500 -> localhost:15000

docker/ibkr-gateway/             # Created by build.yaml
├── Dockerfile                   # Image definition
├── bin/                         # Gateway scripts
├── build/                       # Build artifacts
├── dist/                        # Distribution files
└── root/                        # Gateway config (conf.yaml)

tests/fixtures/playbooks/interactive_brokers/
├── ibkr_api.yaml                # Server/worker API playbook
└── ...

tests/fixtures/credentials/
└── ib_gateway.json.example      # Credential template
```

## Credentials

Create credential file based on template:

```bash
cp tests/fixtures/credentials/ib_gateway.json.example \
   tests/fixtures/credentials/ib_gateway.json
```

Edit with your IBKR credentials:

```json
{
  "name": "ib_gateway",
  "description": "IBKR Client Portal Gateway credentials",
  "type": "http_auth",
  "data": {
    "username": "YOUR_IBKR_USERNAME",
    "account_id": "YOUR_ACCOUNT_ID",
    "environment": "paper",
    "gateway_url": "https://ibkr-client-portal.ibkr.svc.cluster.local:5000",
    "totp_secret": "YOUR_BASE32_TOTP_SECRET"
  }
}
```

Register:

```bash
noetl catalog register tests/fixtures/credentials/ib_gateway.json
```

## Authentication Flow

1. **Deploy gateway**: `noetl run automation/ibkr/deploy.yaml`
2. **Browser login**: Open `https://localhost:15000`, login with IBKR credentials
3. **Session active**: Gateway maintains authenticated session
4. **API calls**: NoETL playbooks call gateway API endpoints
5. **Session keepalive**: Call `/v1/api/tickle` every ~55 seconds

### Authenticate (without IBeam)

This repo includes a small Playwright-based helper that follows the same *high-level* pattern as IBeam
(open the Gateway login page, optionally autofill credentials, handle 2FA if present, then verify via `/v1/api/tickle`).

- Install optional deps via playbook: `noetl run automation/ibkr/setup.yaml`

Run as a NoETL local playbook (manual login):

```bash
noetl run automation/ibkr/login.yaml --payload '{"gateway_url":"https://localhost:15000","manual":true,"paper":true,"timeout_seconds":240}'
```

End-to-end test playbook (setup + manual login + verify):

```bash
noetl run automation/ibkr/test_login.yaml --payload '{"gateway_url":"https://localhost:15000","setup":true,"paper":true,"timeout_seconds":240}'
```

Or run the helper directly:

```bash
python scripts/ibkr/authenticate_gateway.py --gateway-url https://localhost:15000 --manual
```

If you want autofill:

```bash
IBKR_USERNAME=... IBKR_PASSWORD=... python scripts/ibkr/authenticate_gateway.py --paper
```

### Maintain session (tickle/reauth)

Server/worker playbook: `automation/ibkr/maintain` (file: `tests/fixtures/playbooks/interactive_brokers/ibkr_gateway_maintain.yaml`).

- Calls `POST /v1/api/tickle` and returns one of: `noop`, `login_required`, `reauth`, `logout_then_reauth`.
- Uses `POST /v1/api/logout` and `POST /v1/portal/iserver/reauthenticate?force=true` when needed.

The gateway uses self-signed certificates. All HTTP calls must use `verify_ssl: false`.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/api/iserver/auth/status` | GET | Check authentication status |
| `/v1/api/tickle` | POST | Keep session alive |
| `/v1/api/iserver/accounts` | GET | List tradeable accounts |
| `/v1/api/portfolio/{account}/positions/0` | GET | Get positions |
| `/v1/api/iserver/account/orders` | GET | Get orders |
| `/v1/api/iserver/account/orders` | POST | Place order |
| `/v1/api/portfolio/{account}/summary` | GET | Account summary |
| `/v1/api/md/snapshot` | GET | Market data snapshot |

## Troubleshooting

### Gateway not responding

```bash
# Check pod status
kubectl -n ibkr get pods

# Check logs
kubectl -n ibkr logs deployment/ibkr-client-portal

# Restart deployment
kubectl -n ibkr rollout restart deployment/ibkr-client-portal
```

### 401 Unauthorized

Gateway returns 401 when not authenticated. Login via browser at `https://localhost:15000`.

### Session expired

Call tickle endpoint or re-login via browser:

```bash
curl -sk -X POST https://localhost:15000/v1/api/tickle
```

### Port not accessible

Verify kind port mapping exists in `ci/kind/config.yaml`:

```yaml
- containerPort: 30500
  hostPort: 15000
  listenAddress: "127.0.0.1"
  protocol: TCP
```

If cluster was created before port mapping added, recreate cluster:

```bash
kind delete cluster --name noetl
task bring-all  # Recreates cluster with updated config
```
