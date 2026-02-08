---
sidebar_position: 10
title: Development
description: Gateway development setup and architecture
---

# NoETL Gateway

Pure API gateway for NoETL - provides GraphQL and REST interfaces for playbook execution with Auth0 authentication.

## Documentation

For deployment and operations documentation, see:
- [Deployment Guide](./deployment-guide) - Building and deploying to GKE
- [Helm Reference](./helm-reference) - Helm chart configuration
- [Auth0 Setup](./auth0-setup) - Auth0 integration
- [Cloudflare Setup](./cloudflare-setup) - DNS and CDN configuration

## Architecture Principles

**Pure Gateway Design:**
- ✅ No direct database connections
- ✅ All data access through NoETL server API
- ✅ Authentication via NoETL playbooks
- ✅ Stateless request handling
- ✅ GraphQL and REST endpoints only

**What Gateway Does:**
- Exposes GraphQL API for playbook execution
- Provides REST API for Auth0 authentication (`/api/auth/*`)
- Session validation middleware
- Request routing and CORS handling
- API aggregation and orchestration

**What Gateway Does NOT Do:**
- Direct database queries
- Business logic or data processing
- Static file serving (UI served separately from `tests/fixtures/gateway_ui/`)

## Session Caching with NATS K/V

The Gateway uses NATS JetStream K/V as a fast session cache for authentication:

```
Login           → Call playbook → Cache session in NATS K/V
Validate/Auth   → Check NATS K/V → Cache Hit? → Return immediately (no playbook)
                                 → Cache Miss? → Call playbook → Cache result
```

**Architecture:**
- **NATS K/V** (`sessions` bucket): Fast session cache (sub-millisecond lookups, 5 min TTL)
- **PostgreSQL** (`auth` schema): Source of truth for session data
- **NoETL Playbooks**: Handle authentication logic on cache miss

**Benefits:**
- Sub-millisecond session lookups from NATS K/V
- Reduced load on NoETL server and PostgreSQL
- Graceful degradation if NATS K/V is unavailable
- Automatic cache expiration via TTL

**Configuration:**
```bash
# NATS connection with JetStream credentials
export NATS_URL=nats://noetl:noetl@nats.nats.svc.cluster.local:4222
export NATS_SESSION_BUCKET=sessions           # K/V bucket name (default: sessions)
export NATS_SESSION_CACHE_TTL_SECS=300        # TTL in seconds (default: 300 = 5 min)
```

**NATS Server Requirements:**
- JetStream enabled
- Account-based auth with `jetstream: enabled` for the connecting user

See [Auth Integration](./auth-integration) for complete setup.

## API Endpoints

### Public Endpoints
- `GET /health` - Health check
- `POST /api/auth/login` - Authenticate with Auth0 token
- `POST /api/auth/validate` - Validate session token
- `POST /api/auth/check-access` - Check playbook access permission

### Protected Endpoints (Require Authentication)
- `POST /graphql` - Execute playbooks via GraphQL
- `GET /graphql` - GraphiQL playground
- `/noetl/{path}` - Proxy to NoETL server API (all HTTP methods)

### Real-time Callbacks (SSE)
- `GET /events` - SSE connection for real-time playbook results
- `POST /api/internal/callback/async` - Worker callback endpoint
- `POST /api/internal/progress` - Worker progress updates

All auth endpoints delegate to NoETL server playbooks.

## Architecture

Rust-based API gateway that accepts GraphQL requests from the UI and translates them into NoETL playbook executions. Features:

- **Async Callbacks**: Real-time playbook results via SSE (Server-Sent Events)
- **Session Caching**: Sub-millisecond session lookups via NATS K/V
- **Proxy Routes**: Authenticated forwarding to NoETL server API

Integrates with:
- NoETL Server (REST) — default: http://localhost:8082
- NATS (JetStream) — session cache and callback routing

## GraphQL Schema

**Query:**
- `health`: String — basic readiness check
- `version`: String — gateway version

**Mutation:**
- `executePlaybook(name: String!, variables: JSON, clientId: String)`: `Execution` — execute a playbook with optional async callback support

Configuration
-------------
The service is configured via environment variables:

**Server:**
- `ROUTER_PORT` (default: 8090) — HTTP server port
- `NOETL_BASE_URL` (default: http://localhost:8082) — NoETL REST API base URL

**NATS (Callbacks & Session Cache):**
- `NATS_URL` (default: nats://127.0.0.1:4222) — NATS server URL with credentials (e.g., `nats://user:pass@host:port`)
- `NATS_CALLBACK_SUBJECT_PREFIX` (default: noetl.callbacks) — Subject prefix for playbook callbacks
- `NATS_SESSION_BUCKET` (default: sessions) — K/V bucket name for session cache
- `NATS_SESSION_CACHE_TTL_SECS` (default: 300) — Session cache TTL in seconds (5 minutes)
- `NATS_UPDATES_SUBJECT_PREFIX` (default: playbooks.executions.) — Subject prefix for execution updates

## Local Development

Requirements:
- Rust toolchain (stable, 1.83+)

Run:
```bash
cd crates/gateway
cargo run
```

Environment:
```bash
export ROUTER_PORT=8090
export NOETL_BASE_URL=http://localhost:8082
export NATS_URL=nats://127.0.0.1:4222
```

## Docker

Build:
```bash
docker build -t noetl/gateway:dev -f crates/gateway/Dockerfile .
```

Run:
```bash
docker run --rm -p 8090:8090 \
  -e NOETL_BASE_URL=http://host.docker.internal:8082 \
  -e NATS_URL=nats://host.docker.internal:4222 \
  noetl/gateway:dev
```

## Kind Cluster Development

See [dev-commands.md](../development/dev-commands.md) for Kind deployment commands.

## Example: Amadeus AI API Playbook

1. Ensure NoETL server is running at `http://localhost:8082` and NATS at `nats://127.0.0.1:4222`
2. Start the gateway: `cargo run` (from crates/gateway)
3. Open GraphQL Playground at `http://localhost:8090/graphql`
4. Execute mutation:
```graphql
mutation {
  executePlaybook(
    name: "api_integration/amadeus_ai_api"
    variables: { query: "Flights from SFO to JFK tomorrow" }
    clientId: "your-sse-client-id"
  ) {
    id
    executionId
    requestId
    status
  }
}
```

**Getting Results:**
- **SSE (Real-time)**: Connect to `GET /events?session_token=xxx` to receive results via Server-Sent Events
- **Polling**: Query `GET /api/executions/{executionId}` until status is `COMPLETED` or `FAILED`

## Notes

- The gateway proxies `/noetl/*` requests to NoETL server's `/api/*` endpoints
- Session caching via NATS K/V provides sub-millisecond lookups
- SSE callbacks enable real-time playbook result delivery to UI clients

Project Links
-------------
- Tests/fixtures playbooks: `tests/fixtures/playbooks` and `tests/fixtures/playbooks/regression_test`
- NoETL OpenAPI: http://localhost:8082/openapi.json
- tests/fixtures/playbooks/api_integration/amadeus_ai_api


### sqlx-cli

https://docs.rs/crate/sqlx-cli/0.8.2

https://dev.to/behainguyen/rust-sqlx-cli-database-migration-with-mysql-and-postgresql-42gp

- `sqlx migrate add -r my_migration_name`
- write sql scripts
- `sqlx migrate run`
- `sqlx migrate revert`
- `cargo sqlx prepare` (run always after query changing) need update cache for query! macros for all functions 


