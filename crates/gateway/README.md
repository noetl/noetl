# NoETL Gateway

Pure API gateway for NoETL - provides GraphQL and REST interfaces for playbook execution with Auth0 authentication.

## Documentation

For deployment and operations documentation, see:
- [Deployment Guide](../../documentation/docs/gateway/deployment-guide.md) - Building and deploying to GKE
- [Helm Reference](../../documentation/docs/gateway/helm-reference.md) - Helm chart configuration
- [Auth0 Setup](../../documentation/docs/gateway/auth0-setup.md) - Auth0 integration
- [Cloudflare Setup](../../documentation/docs/gateway/cloudflare-setup.md) - DNS and CDN configuration

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

See [AUTH_INTEGRATION.md](AUTH_INTEGRATION.md) for complete setup.

## API Endpoints

### GraphQL
- `POST /graphql` - Execute playbooks (requires authentication)
- `GET /graphql` - GraphiQL playground

### Auth REST API
- `POST /api/auth/login` - Authenticate with Auth0 token
- `POST /api/auth/validate` - Validate session token
- `POST /api/auth/check-access` - Check playbook access permission

All auth endpoints delegate to NoETL server playbooks.

Purpose
-------
Rust-based GraphQL router/proxy that accepts GraphQL requests from the UI and translates them into NoETL playbook executions. In phase 1 we run the playbook and poll NoETL REST for results; in phase 2 we’ll add NATS subscriptions for live updates. It integrates with:

- NoETL Server (REST) — default: http://localhost:8082
- NATS (JetStream-capable) — for distributing updates/events to subscribed clients

Status: Initial scaffold suitable for local development and iterative integration.

Endpoints (Phase 1)
-------------------
- HTTP GraphQL: POST /graphql
- GraphQL Playground: GET /

Notes:
- WebSocket subscriptions (/ws) are disabled in Phase 1. They will return in Phase 2 once NATS/JetStream is enabled.

GraphQL Schema (Phase 1)
------------------------
- Query
  - `health`: String — basic readiness check
- Mutation
  - `executePlaybook(name: String!, variables: JSON)`: `Execution` — requests NoETL to run a playbook

Subscription support will be added in Phase 2.

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

Assumptions and TODO
--------------------
- NoETL REST endpoints: `POST /api/run/playbook` with `{ path, args }` to start an execution. For phase 1, poll the result via `GET /api/executions/{executionId}`.
- NATS subjects (phase 2): The subject naming strategy is a proposal. Adjust to your conventions (JetStream stream/consumer configuration if needed).

Local Development
-----------------
Requirements:
- Rust toolchain (stable)

Run:
```
cargo run
```

Environment (optional):
```
export ROUTER_PORT=8090
export NOETL_BASE_URL=http://localhost:8082
# NATS is not used in Phase 1; keep for future Phase 2
export NATS_URL=nats://127.0.0.1:4222
export NATS_UPDATES_SUBJECT_PREFIX=playbooks.executions.
```

Docker
------
Build:
```
docker build --progress plain -t gateway:local .
```

Run:
```
docker run --rm -p 8090:8090 \
  -e NOETL_BASE_URL=http://host.docker.internal:8082 \
  gateway:local
```

Kubernetes (Kind)
-----------------
Manifests are in `k8s/`. Update environment to match your cluster services (NoETL service DNS). NATS-related envs are currently unused in Phase 1. Then:
```
kubectl apply -f k8s/
```

End-to-end example (Phase 1): Amadeus AI API playbook
-------------------------------------------
A ready-to-run GraphQL example for the playbook `tests/fixtures/playbooks/api_integration/amadeus_ai_api` is provided at:

`tests/fixtures/playbooks/api_integration/amadeus_ai_api/router_example.graphql`

It contains:
- A mutation to execute the playbook via this router
- A subscription example for phase 2 (NATS). For phase 1, use REST polling shown below.

How to run (local):
1. Ensure NoETL server is running at `http://localhost:8082` and NATS at `nats://127.0.0.1:4222`.
2. Start the router (choose one):
   - Rust toolchain (recommended Rust >= 1.83):
     - `cd gateway && cargo run`
   - Docker (uses Rust 1.83 in builder):
     - `docker build -t gateway:local .`
     - `docker run --rm -p 8090:8090 \
         -e NOETL_BASE_URL=http://host.docker.internal:8082 \
         gateway:local`
3. Open GraphQL Playground at `http://localhost:8090/`.
4. Paste the mutation from `router_example.graphql` into the left pane and provide variables like:
```
{
  "vars": {
    "query": "I want a one-way flight from SFO to JFK on March 15, 2026 for 1 adult"
  }
}
```
5. Execute the mutation; copy the returned `id` as `executionId`.
6. Phase 1 (without NATS): Poll NoETL for execution status/result via REST:
```
curl -s http://localhost:8082/api/executions/<executionId> | jq .
```
Look for the latest event status and any `result` payload with the final markdown. You can poll this endpoint until status becomes `COMPLETED` or `FAILED`.

7. Phase 2 (preview): Live subscriptions over WebSocket will be enabled when NATS/JetStream is configured. For now, use REST polling only.

Notes
-----
- The router uses `POST /api/run/playbook` on the NoETL server with body `{ path, args }` to start executions. The `name` GraphQL argument maps to `path` (e.g., `api_integration/amadeus_ai_api`) and `variables` maps to `args`.
- Phase 2 (NATS): subject for updates is `${NATS_UPDATES_SUBJECT_PREFIX}{executionId}.events` (default prefix: `playbooks.executions.`).
- If your local Rust toolchain is older and compilation fails due to dependencies requiring the 2024 edition, run via Docker (builder uses Rust 1.83) or upgrade your local Rust toolchain with `rustup update`.

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


