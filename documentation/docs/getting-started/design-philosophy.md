---
sidebar_position: 5
title: Design Philosophy
description: NoETL's design principles and inspirations
---

# Design Philosophy

NoETL's architecture is informed by several proven paradigms, creating a runtime where tasks are isolated, state transitions are explicit, and AI can optimize execution.

## AI & Domain Data-Driven Design

NoETL is an **AI-data-driven workflow runtime** for domain-centric workloads:

- **Risk and fraud scoring** pipelines
- **Healthcare analytics** for patient cohorts
- **Marketing attribution** and customer 360 views
- **Observability analytics** for SRE teams
- **MLOps** for model training and serving

### Domain-Centric & Data Mesh Aware

Each **playbook** represents a domain workload:
- `risk/score_application`
- `healthcare/patient_cohort`
- `marketing/attribution_model`
- `observability/ingest_traces`

Domains publish **data products** (tables, files, features, embeddings) into a data mesh or lakehouse. NoETL coordinates how those products are:
- Built and refreshed (batch/streaming)
- Validated (schema checks, quality checks)
- Exposed to analytical and AI workloads

### AI-Native Orchestration

NoETL treats every execution as a feedback signal for AI-assisted optimization:

- All **steps**, **retries**, **durations**, and **errors** are recorded as events
- Events are exported to **analytical backends** (ClickHouse, VictoriaMetrics)
- **Vector stores** (Qdrant) enable semantic search across playbooks, logs, and events

AI tasks can then:
- Learn from historical runs
- Tune runtime parameters (batch sizes, retry policies)
- Select optimal hardware per step
- Pick cheaper alternatives for specific domains

## Erlang-Inspired Process Model

From Erlang: **everything is a process**.

- Each workflow execution and step is modeled as an **isolated runtime task**
- Workers run background processes; they do **not** expose HTTP endpoints
- The server acts as **orchestrator and supervisor**:
  - Exposes API endpoints
  - Schedules tasks
  - Handles retries and backoff
  - Records events and state transitions
- The CLI manages lifecycle of servers and worker pools

Components communicate via **events** and persisted state, similar to Erlang's message passing.

## Petri Net-Inspired State & Parallelism

NoETL's workflow model uses explicit state transitions and token-based parallelism:

### States as Places, Steps as Transitions

- Each **step** behaves like a Petri net **transition**
- **Context/result snapshots** between steps behave like **places** holding tokens
- The `next` edges define how tokens flow between states

### Tokens as Data + Context

A "token" is a unit of execution context (workload parameters, step results, domain data references). When a step fires:
1. Consumes incoming tokens
2. Executes its tool
3. Produces new tokens for downstream steps

### Parallelism as Token Fan-Out

- One completed step can produce multiple tokens flowing to different downstream steps
- Those steps run in parallel across worker pools
- Synchronization/joins wait for multiple incoming tokens before firing

### Explicit State Flow

State is not hidden inside arbitrary code:
- Modeled as workflow context (workload → workflow → step → tool)
- Tokens moving along `next` edges
- Persisted events analyzed for each transition

This enables **replay**, **inspection**, and **reasoning** about execution state.

## Rust and Arrow-Informed Data Handling

### Ownership & Borrowing (Rust-Inspired)

Workflow **context** and **results** have clear scopes:
- `workload` → `workflow` → `step` → `tool`

Large domain data objects are passed by **reference** (paths, handles, table names) rather than copying blobs. Shared mutable state is minimized.

### Zero-Copy Data Interchange (Arrow-Inspired)

Tools operate on **structured, columnar data** where possible:
- Arrow-compatible formats (Parquet, Arrow IPC)
- Engine-native tables
- Object storage layouts

The aim is to **borrow** existing representations rather than constantly re-encode, keeping data movement predictable and efficient.

## Summary

By combining these principles, NoETL provides a runtime where:

| Principle | Benefit |
|-----------|---------|
| Erlang processes | Tasks are isolated, failures are supervised |
| Petri net states | State transitions are explicit |
| Rust ownership | Context has clear scope and ownership |
| Arrow interchange | Data moves efficiently without re-encoding |
| AI feedback | System learns and optimizes from executions |

The long-term goal is a **closed-loop control plane** where AI agents continuously propose safe configuration changes — routing, hardware selection, scheduling — based on real execution data.

## See Also

- [Architecture](/docs/getting-started/architecture) - Component overview
- [DSL Reference](/docs/reference/dsl/) - Workflow specification
- [Observability Services](/docs/reference/observability_services) - Analytics stack
