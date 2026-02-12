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
