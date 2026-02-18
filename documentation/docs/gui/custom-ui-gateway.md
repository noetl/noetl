---
title: Build Custom UI with Gateway
description: Gateway-only integration guide for custom UIs that run NoETL playbooks
---

# Build a Custom UI (Gateway-Only)

This guide shows how to build your own frontend (React, Vue, Svelte, plain JS) that talks to **NoETL Gateway only**.

## Architecture Contract

Client UI must call:

- `POST /api/auth/login` (exchange Auth0 token for gateway session token)
- `POST /api/auth/validate` (validate session token)
- `POST /graphql` (playbook execution and GraphQL operations)
- `GET /events` (SSE stream for async playbook callbacks)
- `/{gateway}/noetl/*` (authenticated REST proxy to NoETL `/api/*`)

Client UI must **not** call NoETL server directly (for example `:8082`).

## Environment Variables

Recommended frontend env settings:

```bash
VITE_GATEWAY_URL=https://gateway.mestumre.dev
VITE_AUTH0_DOMAIN=<your-auth0-domain>
VITE_AUTH0_CLIENT_ID=<your-auth0-client-id>
VITE_AUTH0_REDIRECT_URI=https://mestumre.dev/gateway/login
```

## Developer End-to-End Setup (UI + Playbooks)

Use this loop when building your own UI and testing your own playbooks against Gateway.

### 0) Connect local tools to Gateway and NoETL server

If Gateway and NoETL run in GKE, port-forward both services:

```bash
# Terminal 1: Gateway for UI/API calls
kubectl port-forward -n gateway svc/gateway 8091:80

# Terminal 2: NoETL server for register/exec CLI calls
kubectl port-forward -n noetl svc/noetl 8082:8082
```

Set UI and CLI targets:

```bash
export VITE_GATEWAY_URL=http://localhost:8091
export NOETL_SERVER_URL=http://localhost:8082
```

Start your frontend locally:

```bash
cd <your-ui-project>
npm install
npm run dev
```

Optional context setup:

```bash
noetl context add gke-dev --server-url=http://localhost:8082 --runtime=distributed --set-current
noetl context current
```

### 1) Create and register credentials (with `noetl` binary)

Example credential file (`credentials/pg_dev.json`):

```bash
mkdir -p credentials
```

```json
{
  "name": "pg_dev",
  "type": "postgres",
  "description": "Developer Postgres credential",
  "tags": ["dev", "postgres"],
  "data": {
    "db_host": "postgres.postgres.svc.cluster.local",
    "db_port": "5432",
    "db_user": "demo",
    "db_password": "demo",
    "db_name": "demo_noetl"
  }
}
```

Save this JSON to `credentials/pg_dev.json`.

Register credential:

```bash
noetl --server-url "$NOETL_SERVER_URL" register credential --file credentials/pg_dev.json
```

Verify:

```bash
noetl --server-url "$NOETL_SERVER_URL" catalog list Credential
```

### 2) Create and register your playbook

Example playbook (`playbooks/dev/dev_gateway_check.yaml`):

```bash
mkdir -p playbooks/dev
```

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: dev_gateway_check
  path: dev/dev_gateway_check
  description: Verify custom UI -> Gateway -> NoETL execution path

workload:
  query: "select 1 as ok"

workflow:
  - step: db_check
    tool:
      kind: postgres
      auth: pg_dev
      query: "{{ workload.query }}"
```

Save this YAML to `playbooks/dev/dev_gateway_check.yaml`.

Register playbook:

```bash
noetl --server-url "$NOETL_SERVER_URL" register playbook --file playbooks/dev/dev_gateway_check.yaml
```

Verify:

```bash
noetl --server-url "$NOETL_SERVER_URL" catalog list Playbook
```

### 3) Run playbook directly with `noetl` binary

```bash
noetl --server-url "$NOETL_SERVER_URL" exec dev/dev_gateway_check -r distributed --json
```

Check status by execution ID:

```bash
noetl --server-url "$NOETL_SERVER_URL" status <EXECUTION_ID> --json
```

### 4) Run the same playbook from your custom UI through Gateway

1. Start your frontend dev server (React/Vue/Svelte/etc.) with `VITE_GATEWAY_URL` set.
2. Authenticate via Auth0 and exchange token at `POST /api/auth/login`.
3. Open SSE `GET /events` and capture `clientId`.
4. Execute GraphQL mutation:

```graphql
mutation ExecuteAsync($vars: JSON!, $clientId: String!) {
  executePlaybook(
    name: "dev/dev_gateway_check"
    variables: $vars
    clientId: $clientId
  ) {
    executionId
    requestId
    status
  }
}
```

Variables:

```json
{
  "vars": {
    "query": "select now() as ts"
  },
  "clientId": "<SSE_CLIENT_ID>"
}
```

This validates the full path:
`Custom UI -> Gateway (/graphql) -> NoETL playbook -> SSE callback`.

## 1) Login and Session Token

After obtaining Auth0 ID token in your UI:

```ts
const gatewayBase = import.meta.env.VITE_GATEWAY_URL;

const loginRes = await fetch(`${gatewayBase}/api/auth/login`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    auth0_token: idToken,
    auth0_domain: import.meta.env.VITE_AUTH0_DOMAIN,
  }),
});

const loginData = await loginRes.json();
const sessionToken = loginData.session_token;
```

Validate and reuse the token:

```ts
await fetch(`${gatewayBase}/api/auth/validate`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ session_token: sessionToken }),
});
```

## 2) Execute Playbook via GraphQL

```ts
const query = `
mutation Execute($name: String!, $vars: JSON!) {
  executePlaybook(name: $name, variables: $vars) {
    executionId
    status
  }
}`;

const gqlRes = await fetch(`${gatewayBase}/graphql`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    Authorization: `Bearer ${sessionToken}`,
  },
  body: JSON.stringify({
    query,
    variables: {
      name: "api_integration/amadeus_ai_api",
      vars: { origin: "SFO", destination: "JFK" },
    },
  }),
});
```

## 3) Async Results via SSE (Recommended)

Open SSE first:

```ts
const sse = new EventSource(
  `${gatewayBase}/events?session_token=${encodeURIComponent(sessionToken)}`
);
```

Read init message to capture `clientId`, then call GraphQL with `clientId`:

```graphql
mutation ExecuteAsync($name: String!, $vars: JSON!, $clientId: String!) {
  executePlaybook(name: $name, variables: $vars, clientId: $clientId) {
    executionId
    requestId
    status
  }
}
```

Gateway sends callback events on SSE when playbook completes.

## 4) Use REST Proxy for NoETL APIs

Gateway forwards `/noetl/<path>` to NoETL `/api/<path>`.

Example:

```ts
await fetch(`${gatewayBase}/noetl/catalog/list`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    Authorization: `Bearer ${sessionToken}`,
  },
  body: JSON.stringify({ resource_type: "Playbook" }),
});
```

## Production Checklist

- UI origin is included in gateway CORS (for example `https://mestumre.dev`)
- UI calls `https://gateway.mestumre.dev` only
- Cloudflare cache bypass rule for:
  - `gateway.mestumre.dev/api/*`
  - `OPTIONS` requests
- `Authorization: Bearer <session_token>` added for `/graphql` and `/noetl/*`

## DNS Quick Copy

Use one of these Cloudflare layouts:

Option A (GUI on apex `mestumre.dev`):

- `A @ -> 35.226.162.30` (Proxied)
- `A gateway -> 34.46.180.136` (Proxied)

Option B (keep existing apex CNAME, GUI on subdomain):

- `CNAME @ -> c.storage.googleapis.com` (Proxied)
- `A gui -> 35.226.162.30` (Proxied)
- `A gateway -> 34.46.180.136` (Proxied)
