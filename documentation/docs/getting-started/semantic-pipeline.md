---
sidebar_position: 5
title: Semantic Pipeline
description: AI-powered execution analysis with embeddings and LLM reasoning
---

# Semantic Execution Pipeline

NoETL includes an AI-powered semantic pipeline that enables intelligent analysis of workflow executions using embeddings, vector search, and LLM reasoning.

## Pipeline Overview

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
     │ - HNSW vector search                   │
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

## Components

### 1. NoETL Server

- Validates playbooks against schema
- Creates workload instances
- Publishes commands to NATS JetStream

### 2. NoETL Workers

- Pull tasks from `NOETL_COMMANDS` stream
- Execute tasks (python, http, postgres, etc.)
- Emit detailed events back to server

### 3. Event Processor

- Normalizes events (`task_start`, `task_end`, `error`, `retries`)
- Builds structured execution traces
- Indexes metadata for search

### 4. Embedding Pipeline

For each execution event:
1. Extract message text, error descriptions, metadata
2. Convert to embedding vectors using embedding models
3. Store vectors in Qdrant with metadata reference

### 5. Semantic Search (Qdrant)

Enables intelligent queries:
- Find similar failures
- Cluster executions by behavior
- Show similar playbooks
- Detect anomalies

### 6. LLM Reasoning Layer

Retrieves top-k relevant context from Qdrant and produces:
- **Explanations**: Why did this step fail?
- **Recommendations**: Fix missing credential, increase batch size
- **Optimization**: Parallelize steps X and Y
- **Auto-generation**: Suggested retry logic adjustments

## Use Cases

### Root Cause Analysis

When a workflow fails:
1. Embed the error message and context
2. Search for similar past failures
3. LLM analyzes patterns and suggests fixes

### Workflow Optimization

Based on execution history:
1. Identify slow steps across executions
2. Find similar successful workflows
3. Recommend parallelization or batching

### Anomaly Detection

Monitor for unusual patterns:
1. Embed execution metrics
2. Detect outliers in vector space
3. Alert on significant deviations

## Infrastructure

### Qdrant Vector Database

- **HTTP API**: http://localhost:30633
- **gRPC**: localhost:30634
- Storage: 5GB default allocation

### Deployment

```bash
# Deploy observability stack (includes Qdrant)
task observability:activate-all

# Check status
task observability:status-all
```

## See Also

- [Observability Services](/docs/reference/observability_services) - Full observability stack
- [ClickHouse Integration](/docs/reference/clickhouse_observability) - Analytics database
- [Architecture](/docs/getting-started/architecture) - System overview
