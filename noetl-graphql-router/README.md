NoETL GraphQL Router
====================

Purpose
-------
Rust-based GraphQL router/proxy that accepts GraphQL queries and subscriptions from the UI and translates them into NoETL playbook executions and event streams. It integrates with:

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
- Subscription
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
- NoETL REST endpoints: Exact paths and payloads will be aligned with your server. The client currently targets placeholder endpoints and should be updated against the live OpenAPI: http://localhost:8082/openapi.json
- NATS subjects: The subject naming strategy is a proposal. Adjust to your conventions (JetStream stream/consumer configuration if needed).

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

Project Links
-------------
- Tests/fixtures playbooks: `tests/fixtures/playbooks` and `tests/fixtures/playbooks/regression_test`
- NoETL OpenAPI: http://localhost:8082/openapi.json
