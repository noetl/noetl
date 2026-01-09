---
sidebar_position: 1
title: NoETL
slug: /intro
description: Automation framework for Data Mesh and MLOps orchestration
---

# NoETL

**NoETL** is an automation framework for Data Mesh and MLOps orchestration.

![NoETL System Diagram](https://raw.githubusercontent.com/noetl/noetl/HEAD/documentation/static/img/noetl-main.png)

## What is NoETL?

NoETL is an **AI-data-driven workflow runtime** designed for domain-centric data products and AI workloads:

- **Data Mesh & Lakehouse** - Domain teams own their pipelines while sharing the same runtime
- **MLOps Orchestration** - Feature engineering, model training, and online scoring
- **Analytical Workloads** - Risk scoring, healthcare analytics, marketing attribution
- **Observability Analytics** - SRE and platform team automation

## Key Capabilities

| Capability | Description |
|------------|-------------|
| **Declarative DSL** | YAML-based playbooks with Jinja2 templating |
| **Multi-Tool Execution** | HTTP, Python, PostgreSQL, DuckDB, Snowflake, and more |
| **Distributed Workers** | Horizontal scaling with stateless worker pools |
| **Event-Driven** | All execution emits structured events for analytics |
| **AI-Native** | Semantic search and LLM reasoning over executions |

## Quick Links

- [Quick Start](/docs/getting-started/quickstart) - Get running in minutes
- [Installation](/docs/getting-started/installation) - PyPI and Kubernetes setup
- [Playbook Structure](/docs/features/playbook_structure) - Learn the DSL
- [DSL Reference](/docs/reference/dsl/) - Complete specification

## Architecture Overview

NoETL follows a server-worker architecture:

- **Server**: Orchestration + REST API (catalog, credentials, events)
- **Workers**: Stateless executors that run workflow steps
- **CLI**: Manages server/worker lifecycle and catalog operations

For detailed architecture, see [Architecture](/docs/getting-started/architecture).

## Design Philosophy

NoETL takes inspiration from:

- **Erlang** - Everything is a process; isolate and supervise failures
- **Rust** - Explicit ownership of data and context
- **Petri Nets** - Explicit state transitions and token-based parallelism
- **Apache Arrow** - Zero-copy data interchange

Learn more in [Design Philosophy](/docs/getting-started/design-philosophy).
