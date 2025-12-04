NoETL GraphQL Router
====================

Purpose
-------
Rust-based GraphQL router/proxy that accepts GraphQL requests from the UI and translates them into NoETL playbook executions. In phase 1 we run the playbook and poll NoETL REST for results; in phase 2 we’ll add NATS subscriptions for live updates. It integrates with:

- NoETL Server (REST) — default: http://localhost:8082
- NATS (JetStream-capable) — for distributing updates/events to subscribed clients

Status: Initial scaffold suitable for local development and iterative integration.

Endpoints
---------
- HTTP GraphQL: POST /graphql
- GraphQL Playground: GET /
- GraphQL Subscriptions (WebSocket): GET /ws

GraphQL Schema (initial)
------------------------
- Query
  - `health`: String — basic readiness check
- Mutation
  - `executePlaybook(name: String!, variables: JSON)`: `Execution` — requests NoETL to run a playbook
- Subscription (phase 2)
  - `playbookUpdates(executionId: ID!)`: `JSON` — streams events for a given playbook execution via NATS

Configuration
-------------
The service is configured via environment variables:

- `ROUTER_PORT` (default: 8090) — HTTP server port
- `NOETL_BASE_URL` (default: http://localhost:8082) — NoETL REST API base URL
- `NATS_URL` (default: nats://127.0.0.1:4222) — NATS connection URL
- `NATS_UPDATES_SUBJECT_PREFIX` (default: playbooks.executions.) — Subject prefix for updates; final subject is `${prefix}{executionId}.events`

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
export NATS_URL=nats://127.0.0.1:4222
export NATS_UPDATES_SUBJECT_PREFIX=playbooks.executions.
```

Docker
------
Build:
```
docker build -t noetl-graphql-router:local .
```

Run:
```
docker run --rm -p 8090:8090 \
  -e NOETL_BASE_URL=http://host.docker.internal:8082 \
  -e NATS_URL=nats://host.docker.internal:4222 \
  noetl-graphql-router:local
```

Kubernetes (Kind)
-----------------
Manifests are in `k8s/`. Update environment to match your cluster services (NoETL service DNS, NATS, etc.). Then:
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
     - `cd noetl-graphql-router && cargo run`
   - Docker (uses Rust 1.83 in builder):
     - `docker build -t noetl-graphql-router:local .`
     - `docker run --rm -p 8090:8090 \
         -e NOETL_BASE_URL=http://host.docker.internal:8082 \
         -e NATS_URL=nats://host.docker.internal:4222 \
         noetl-graphql-router:local`
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

7. Phase 2 (optional preview): You can also try the subscription snippet in `router_example.graphql` over `ws://localhost:8090/ws` once NATS is configured in your environment.

Notes
-----
- The router uses `POST /api/run/playbook` on the NoETL server with body `{ path, args }` to start executions. The `name` GraphQL argument maps to `path` (e.g., `api_integration/amadeus_ai_api`) and `variables` maps to `args`.
- Phase 2 (NATS): subject for updates is `${NATS_UPDATES_SUBJECT_PREFIX}{executionId}.events` (default prefix: `playbooks.executions.`).
- If your local Rust toolchain is older and compilation fails due to dependencies requiring the 2024 edition, run via Docker (builder uses Rust 1.83) or upgrade your local Rust toolchain with `rustup update`.

Project Links
-------------
- Tests/fixtures playbooks: `tests/fixtures/playbooks` and `tests/fixtures/playbooks/regression_test`
- NoETL OpenAPI: http://localhost:8082/openapi.json
