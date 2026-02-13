---
title: GUI Run and Test Guide
slug: /gui
description: How to run and test the NoETL GUI in gateway-only mode
---

# NoETL GUI (Gateway-Only)

This guide explains how to run and validate the NoETL GUI located at:

- `/Volumes/X10/projects/noetl/noetl/gui`

The GUI is configured to use **NoETL Gateway only** (no direct NoETL API access).

For teams building a custom frontend, see:

- [Build Custom UI with Gateway](./gui/custom-ui-gateway)

## Prerequisites

- Node.js 20+ (or a compatible Node.js runtime)
- npm
- Running NoETL Gateway endpoint (default: `http://localhost:8090`)

## Environment Variables

Set these in your shell before running the GUI:

```bash
export VITE_GATEWAY_URL="http://localhost:8090"
export VITE_AUTH0_DOMAIN="<your-auth0-domain>"
export VITE_AUTH0_CLIENT_ID="<your-auth0-client-id>"
# Optional override:
# export VITE_AUTH0_REDIRECT_URI="http://localhost:3001/gateway/login"
```

## Auth0 Application Settings (Required)

In your Auth0 Application (client id `Jqop7YoaiZalLHdBRo5ScNQ1RJhbhbDN`), add exact URLs:

- **Allowed Callback URLs**:
  - `https://mestumre.dev/gateway/login`
  - `https://gui.mestumre.dev/gateway/login` (if using subdomain UI)
  - `http://localhost:3001/gateway/login`
- **Allowed Logout URLs**:
  - `https://mestumre.dev`
  - `https://gui.mestumre.dev`
  - `http://localhost:3001`
- **Allowed Web Origins**:
  - `https://mestumre.dev`
  - `https://gui.mestumre.dev`
  - `https://gateway.mestumre.dev`
  - `http://localhost:3001`

`redirect_uri` must match one of Allowed Callback URLs exactly or Auth0 returns `Callback URL mismatch`.

## Run Locally

From the project root:

```bash
cd gui
npm install
npm run dev
```

Default local GUI URL:

- `http://localhost:3001`

## Validate Build and Types

Run from `gui`:

```bash
npm run type-check
npm run build
```

Expected behavior:

- `type-check` exits with code `0`
- `build` generates `gui/dist`

## GKE Pinned Deploy Command (Keep This)

Use this command to redeploy with pinned static IPs for gateway and GUI:

```bash
noetl run automation/gcp_gke/noetl_gke_fresh_stack.yaml \
  --set action=deploy \
  --set project_id=noetl-demo-19700101 \
  --set region=us-central1 \
  --set cluster_name=noetl-cluster \
  --set deploy_ingress=false \
  --set build_images=false \
  --set deploy_clickhouse=false \
  --set gateway_service_type=LoadBalancer \
  --set gateway_load_balancer_ip=34.46.180.136 \
  --set gui_service_type=LoadBalancer \
  --set gui_load_balancer_ip=35.226.162.30
```

Current pinned values:

- Gateway: `34.46.180.136`
- GUI: `35.226.162.30`

## Gateway-Only Verification Checklist

1. Confirm `VITE_GATEWAY_URL` is set to your gateway host.
2. Open browser dev tools and inspect network requests:
   - Auth calls should go to `${VITE_GATEWAY_URL}/api/auth/*`
   - GraphQL calls should go to `${VITE_GATEWAY_URL}/graphql`
   - API calls should go to `${VITE_GATEWAY_URL}/api/*`
3. Verify there are no direct calls to legacy NoETL API hosts (for example `localhost:8082`).

## Basic Smoke Test

1. Open `http://localhost:3001/gateway/login`
2. Sign in with Auth0 (or test session token)
3. Navigate to Gateway page
4. Submit a test query (for example: `I want to fly from SFO to JFK tomorrow`)
5. Verify:
   - SSE connection state becomes connected
   - Playbook response is returned in chat
   - No unauthorized direct API calls appear in network logs

## Troubleshooting

- **401 / Session expired**
  - Re-authenticate via `/gateway/login`
  - Confirm gateway session validation endpoint is reachable

- **SSE not connecting**
  - Verify gateway `/events` endpoint availability
  - Check browser network/CORS settings and token validity

- **Build works but runtime API fails**
  - Confirm `VITE_GATEWAY_URL` points to the correct gateway environment
  - Ensure gateway routes `/api/*`, `/graphql`, and `/events` are exposed
