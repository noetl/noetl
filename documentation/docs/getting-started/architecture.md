---
sidebar_position: 3
title: Architecture
description: NoETL system architecture and components
---

# Architecture

NoETL uses a server-worker architecture for distributed workflow execution.

## Component Overview

![NoETL Components](https://raw.githubusercontent.com/noetl/noetl/HEAD/documentation/static/img/noetl-components.png)

## Components

### Gateway/API

External entrypoint exposing the public HTTP API:
- Handles authentication and authorization
- Forwards requests to the Server
- Used by CLIs, UIs, and integrations

### Orchestrator Server

Central coordination service:
- Schedules and supervises workflow executions
- Manages retries and backoff policies
- Records events to the event log
- Provides CRUD APIs for catalog, credentials, tasks, and events

### Worker Pools

Stateless background executors:
- Run workflow steps and tools (HTTP, SQL, Python, etc.)
- Scale horizontally based on load
- No inbound HTTP endpoints (pull-based)
- Isolated execution environments

### Scheduler & Queues

Internal task management:
- Priority queues for task scheduling
- Resource-aware scheduling (CPU/GPU pools, concurrency limits)
- Handles fan-out/fan-in patterns
- Back-pressure management across workflows

### Catalog & Credentials

Storage for workflow definitions:
- **Catalog**: Playbooks, versions, schemas, tool definitions
- **Credentials**: Connection configs and tokens with scoped access

### Event Bus and Telemetry

Observability infrastructure:
- Every step emits structured events (start/finish/errors, durations)
- Events exported to analytics backends (ClickHouse, VictoriaMetrics)
- Vector stores (Qdrant) for AI-assisted optimization and semantic search

### Storage/Compute Integrations

Connectors for external systems:
- Warehouses: DuckDB, PostgreSQL, ClickHouse, Snowflake
- Files/Lakes: GCS, S3, local filesystem
- Vector DBs: Qdrant
- External services: HTTP APIs

## Data Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Client    │────▶│   Server    │────▶│   Workers   │
│  (CLI/API)  │     │ (Orchestr.) │     │  (Execute)  │
└─────────────┘     └──────┬──────┘     └──────┬──────┘
                           │                    │
                           ▼                    ▼
                    ┌─────────────┐     ┌─────────────┐
                    │  PostgreSQL │     │   Events    │
                    │  (Catalog)  │     │  (Logs/Obs) │
                    └─────────────┘     └─────────────┘
```

1. **Client** submits playbook via CLI or API
2. **Server** validates and schedules execution
3. **Server** enqueues jobs to PostgreSQL queue
4. **Workers** poll queue, execute steps, report results
5. **Events** recorded for observability and AI analysis

## Workflow Block Schema

![NoETL Workflow Block Schema](https://raw.githubusercontent.com/noetl/noetl/HEAD/documentation/static/img/noetl-block-schema.png)

## Communication Patterns

### Server ↔ Worker

Workers communicate with the server via:
- **PostgreSQL Queue**: Job leasing and result reporting
- **Events API**: Step execution events

### Event-Driven State

All execution state is persisted as events:
- Server reconstructs state from event log
- Enables replay and debugging
- Supports distributed execution

## Scaling

### Horizontal Scaling

- **Workers**: Add more worker replicas for throughput
- **Server**: Single server coordinates all executions
- **Database**: PostgreSQL handles concurrent access

### Resource Pools

Configure worker pools for different resource types:
- CPU-intensive workloads
- GPU workloads (future)
- I/O-bound operations

## See Also

- [Design Philosophy](/docs/getting-started/design-philosophy) - Architectural principles
- [Observability Services](/docs/reference/observability_services) - Monitoring stack
- [Multiple Workers](/docs/development/multiple_workers) - Worker configuration
