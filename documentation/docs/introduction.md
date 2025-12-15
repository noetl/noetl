---
sidebar_position: 1
title: Introduction
description: Overview, Architecture, and Semantic Execution Pipeline for NoETL
---

# Introduction

NoETL is an automation framework for Data Mesh and MLOps orchestration. This introduction covers the high-level system overview, component architecture, and the AI/semantic execution pipeline.

## Overview

The following diagram illustrates the main parts and intent of the NoETL system:

![NoETL System Diagram](https://raw.githubusercontent.com/noetl/noetl/HEAD/documentation/static/img/noetl-main.png)

- Server: orchestration + API endpoints (catalog, credentials, tasks, events)
- Worker: background worker pool, no HTTP endpoints
- Noetl CLI: manages worker pools and server lifecycle

## Architecture

The following component view shows how NoETL is structured and how requests/data flow between parts of the system:

![NoETL Components](https://raw.githubusercontent.com/noetl/noetl/HEAD/documentation/static/img/noetl-components.png)

- Gateway/API
  - External entrypoint that exposes the public HTTP API used by CLIs, UIs, and integrations.
  - Handles authn/z and forwards requests to the Server.
- Orchestrator Server
  - Schedules and supervises workflow executions, manages retries/backoff, and records events.
  - Provides CRUD APIs for catalog (playbooks, tools), credentials, tasks, and events.
- Worker Pools
  - Stateless/background executors that run workflow steps and tools (HTTP, SQL engines, vector DBs, Python, etc.).
  - Scaled horizontally; no inbound HTTP endpoints.
- Scheduler & Queues
  - Internal priority queues for tasks, with resource-aware scheduling (CPU/GPU pools, concurrency limits).
  - Handles fan-out/fan-in and back-pressure across workflows, inspired by Petri nets.
- Catalog & Credentials
  - Catalog stores playbooks, versions, schemas, and tool definitions.
  - Credentials vault keeps connection configs and tokens with scoped access for steps.
- Event Bus and Telemetry
  - Every step emits structured events (start/finish/errors, durations, resource usage).
  - Events are exported to analytics backends (e.g., ClickHouse, VictoriaMetrics/Logs) and vector stores (e.g., Qdrant) for AI-assisted optimization and semantic search.
- Storage/Compute Integrations
  - Connectors for warehouses (DuckDB, Postgres, ClickHouse), files/lakes, vector DBs, and external services.
  - Results and artifacts are published as domain data products in a mesh/lakehouse.

This architecture enables domain-centric, AI-informed orchestration: the Server coordinates state and scheduling; Workers execute steps; telemetry and embeddings feed back into policies that optimize routing, hardware selection, and retry strategies over time.


### Workflow Block Schema

![NoETL Workflow Block Schema](https://raw.githubusercontent.com/noetl/noetl/HEAD/documentation/static/img/noetl-block-schema.png)


![NoETL Semantic Execution Pipeline](https://raw.githubusercontent.com/noetl/noetl/HEAD/documentation/static/img/semantic.png)


#### How the Components Work Together

1. NoETL Server
   - Validates the playbook
   - Creates workload instance
   - Publishes initial commands into JetStream

2. NoETL Workers
   - Pull tasks from `NOETL_COMMANDS` NATS JetStreams
   - Execute tasks (python, http, postgres, etc.)
   - Emit detailed events back to Control Plane API

3. Event Processor
   - Normalizes events (`task_start`, `task_end`, `error`, `retries`)
   - Builds structured execution trace

4. Embedding Pipeline
   - For each execution event:
     - Extract message text, error descriptions, metadata
     - Convert to embedding vectors
     - Store vectors in Qdrant with metadata reference

5. Semantic Search (Qdrant)
   - Enables:
     - Find similar failures
     - Cluster executions by behavior
     - Show similar playbooks
     - Detect anomalies

6. LLM Reasoning Layer
   - Retrieves the top-k relevant context from Qdrant and produces:
     - Explanations (Why this step failed?)
     - Recommendations (Fix missing credential, Increase batch size)
     - Workflow optimization (Parallelize steps X and Y)
     - Auto-generated steps / retry logic adjustments


## AI & Domain Data-Driven Design

NoETL is an **AI-data-driven workflow runtime** for **domain-centric** Data Mesh, Data Lakehouse, Analytical, MLOps, and general automation workloads.

Instead of being just ETL, NoETL is intended to sit at the center of **domain data products** and **AI workloads**:
- risk and fraud scoring pipelines,
- patient and cohort analytics in healthcare,
- recommendation and ranking systems in e-commerce,
- marketing attribution and customer 360 views,
- operations / observability analytics for SRE & platform teams.

It takes inspiration from:

- **Erlang** – everything is a process; isolate failures and supervise them.
- **Rust** – explicit ownership and borrowing of data; minimize unsafe sharing, applied to data governance and analytics.
- **Petri nets** – explicit modeling of state transitions and token-based parallelism in workflows.
- **Zero-copy data interchange** – Apache Arrow style memory layouts for sharing data without re-serialization.

### Domain-Centric & Data Mesh Aware

NoETL assumes that data and AI are **domain-specific**:

- Each **playbook** is a domain workload:
  - e.g. `risk/score_application`, `healthcare/patient_cohort`, `marketing/attribution_model`, `observability/ingest_traces`.
- Domains publish **data products** (tables, files, features, embeddings, metrics) into a **data mesh** or **data lakehouse**.
- NoETL coordinates how those products are:
  - built and refreshed (batch / streaming),
  - validated (schema checks, quality checks),
  - exposed to analytical and AI workloads (SQL engines, vector DBs, APIs).

This makes NoETL a good fit for organizations that want domain teams (risk, clinical, marketing, ops, etc.) to own their pipelines independently, while sharing the same runtime.

### AI-Native & Data-Driven Orchestration

NoETL treats every execution as a feedback signal for **AI-assisted optimization**:

- All **steps**, **retries**, **durations**, **error types**, and **resource usages** are recorded as events.
- These events are exported to **analytical backends** (ClickHouse, VictoriaMetrics, VictoriaLogs) and **AI-centric stores** (Qdrant for embeddings and semantic search across playbooks, logs, events, and domain artifacts).
- Domain-specific AI tasks can then:
  - learn from historical runs (e.g. which features are expensive, which steps are flaky in data processing, where fraud models time out),
  - tune **runtime parameters** (batch sizes, sampling, routing, retry policies, pool limits),
  - select **optimal runtime hardware** per step (CPU class, GPU type, accelerator pool, quantum API backends) based on observed latency, throughput, and cost,
  - pick cheaper or safer alternatives for specific domains (e.g. use cached features for credit scoring, downsample telemetry for observability workloads, or route heavy semantic queries to cheaper vector backends).

Typical AI workloads orchestrated by NoETL include:

- **RAG and semantic search** pipelines for documentation, logs, metrics, and domain records (backed by Qdrant or other vector stores),
- **Feature engineering** and **feature store** feeds for ML models,
- **Model training and evaluation** for domain models (risk, clinical, marketing, operations),
- **Online scoring** pathways that fan out to vector DBs, warehouses, services, and specialized hardware (CPU/GPU/accelerator/quantum endpoints).

At runtime, hardware capabilities are modeled as part of the resource pools: playbooks and steps can declare hardware preferences or constraints, and AI policies can decide how to map those steps onto available CPU, GPU, or quantum-style backends.

The long-term goal is a **closed-loop control plane** where AI agents continuously propose and apply safe configuration changes for each domain — routing, hardware selection, and scheduling policies — based on real execution data and semantic understanding of past workloads.

### Petri Net Inspired State & Parallelism

NoETL’s workflow model is also inspired by **Petri nets**: parallelism and state are made explicit, and **data moves from state to state** in a controlled way.

- **States as places, steps as transitions**
  - Each **step** in a workflow behaves like a Petri net **transition**.
  - The **context/result snapshots** between steps behave like **places** that hold tokens.
  - The `next` edges (with optional `when` and `args`) define how tokens flow from one state to another.

- **Tokens as data + context**
  - A “token” corresponds to a unit of execution context (workload parameters, step results, domain data references).
  - When a step fires, it:
    - consumes one or more incoming tokens,
    - executes its tool (`http`, `python`, `postgres`, `duckdb`, `clickhouse`, `qdrant`, etc.),
    - produces new tokens with updated context/results for downstream steps.

- **Parallelism as token fan-out**
  - Parallel branches are modeled by **fan-out in the Petri net**:
    - one completed step can produce multiple tokens that flow into different downstream steps,
    - those downstream steps can run in parallel across worker pools.
  - Synchronization / joins are modeled by steps that wait for multiple incoming tokens (fan-in) before firing.

- **State management as explicit flow**
  - State is not hidden inside arbitrary code; it is modeled as:
    - workflow context (workload → workflow → step → tool),
    - tokens moving along `next` edges,
    - persisted events analyzed for each transition.
  - This makes it possible to **replay**, **inspect**, and **reason about** execution state in the same way Petri nets allow analysis of reachability and invariants.

### Erlang Inspired Process Model

NoETL follows Erlang’s idea that **everything is a process**:

- Each workflow execution, and each step within it, is modeled as an **isolated runtime task**.
- Worker pools run background workers that execute these tasks; workers do **not** expose HTTP endpoints.
- The server acts as the **orchestrator and supervisor**:
  - exposes API endpoints (catalog, credentials, events),
  - schedules tasks,
  - handles retries and backoff,
  - records events and state transitions,
  - keeps failures local to the affected execution or domain.
- The CLI manages the lifecycle of servers and worker pools (start, stop, scale).

Components communicate via **events** and persisted state (Postgres, NATS JetStream, logs/metrics), similar to Erlang processes communicating via message passing.

### Rust and Arrow Informed Data Handling

NoETL’s data model borrows ideas from Rust and Apache Arrow:

- **Ownership & borrowing semantics (Rust inspired)**
  - Workflow **context** and **results** have clear scopes: workload → workflow → step → tool.
  - Large domain data objects (tables, feature sets, parquet files, embeddings) are passed by **reference** (paths, handles, table names) rather than blindly copying blobs.
  - Shared mutable state is minimized; each step “owns” its slice of context while it runs, then publishes results back into well-defined domain products.

- **Zero-copy and columnar sharing (Arrow inspired)**
  - Tools like DuckDB, ClickHouse, Postgres, and vector databases operate on **structured, columnar data** where possible.
  - Domain pipelines are encouraged to share data via:
    - Arrow-compatible formats (Parquet, Arrow IPC),
    - engine-native tables,
    - object storage layouts,
    instead of repeatedly serializing/deserializing huge JSON payloads.
  - The aim is to **borrow** existing representations rather than constantly re-encode them, keeping data movement predictable and efficient across domains.

By combining **Erlang style processes**, **Rust-like ownership of context**, **Arrow-style zero-copy data interchange**, and **Petri net-style state and parallelism**, NoETL provides a runtime where:

- tasks are isolated,
- state transitions are explicit,
- parallelism is structurally visible,
- and AI/analytics can safely optimize how data flows from one state to another.

Together, these principles give NoETL a clear stance:

- Treat each domain workload as a **process** that can fail, restart, and be supervised.
- Treat data as something that should be **borrowed and shared safely**, not constantly cloned.
- Use **AI and domain-specific analytics** over past executions to continuously improve how the system schedules, routes, and scales workflows across data mesh/lakehouse, analytical, and MLOps domains.

## NoETL Semantic Execution Pipeline (Embeddings + Qdrant + LLM)

```
                            ┌──────────────────────────────┐
                            │        Business User UI      │
                            │ (GraphQL/Gateway/API Client) │
                            └───────────────┬──────────────┘
                                            │
                                            ▼
                                ┌──────────────────────┐
                                │     NoETL Server     │
               _________________│ - Validates playbook │
              |                 │ - Creates workload   │
              |                 │ - Publishes commands │
              |                 └─────────────┬────────┘
              │(NATS JetStream)               | 
              |                               | 
     ┌────────▼──────────────────┐     ┌-─────▼─────────────────────┐
     │       JetStream           │     │        NoETL Workers       │
     │                           │     │ - Pull commands            │
     │  - NOETL_COMMANDS Stream  │◀────│ - Run tools / tasks        │
     └──────────────────────────-┘     │ - Emit results + logs      │
                                       └──────────-┬────────────────┘
                               (event log messages)│
                                                   │
      ┌─────────────────────────────┐              │
      │ NoETL Server Event Handler  │◀─────────────┘
      │ - Collects events           |
      | - Execution Events          │
      │ - Normalizes + indexes      │
      │ - Stores metadata           │
      └──────────────┬──────────────┘
                     │
                     ▼
   ┌──────────────────────────────────────────────────┐
   │            Embedding + Semantic Layer            │
   │--------------------------------------------------│
   │                                                  │
   │ 1. Convert events/workloads/logs to embeddings   │
   │      using local/OpenAI embedding models         │
   │                                                  │
   │ 2. Store vectors in Qdrant (vector database)     │
   │      - Similar executions                        │
   │      - Error clusters                            │
   │      - Semantic search index                     │
   │                                                  │
   └───────────────┬──────────────────────────────────┘
                   │
                   ▼
     ┌────────────────────────────────────────┐
     │              Qdrant Vector DB          │
     │ - Annoy/HNSW vector search             │
     │ - Top-K nearest neighbors              │
     │ - Semantic relevance ranking           │
     └───────────────┬────────────────────────┘
                     │ (retrieved context)
                     ▼
         ┌────────────────────────────┐
         │            LLM             │
         │  (OpenAI / Local Model)    │
         │----------------------------│
         │ - Root-cause analysis      │
         │ - Explain execution flows  │
         │ - Recommend next actions   │
         │ - Optimize retries/loops   │
         │ - Generate workflow steps  │
         └───────────────┬────────────┘
                         │
                         ▼
              ┌───────────────────────────┐
              │  Insights / AI Assistant  │
              │ - Why did this fail?      │
              │ - Show similar workflows  │
              │ - Predict bottlenecks     │
              │ - Recommend improvements  │
              └───────────────────────────┘
```
