---
sidebar_position: 1
title: Installation
description: Install NoETL for local development or production deployment
---

# Installation

NoETL can be installed for local development or deployed to Kubernetes for production use.

## Quick Start (pip)

The simplest way to get started:

```bash
# Install from PyPI
pip install noetl

# Verify installation
noetl --version
```

## Development Installation

For contributing or local development:

```bash
# Clone repository
git clone https://github.com/noetl/noetl.git
cd noetl

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install in development mode
pip install -e ".[dev]"

# Verify CLI
noetl --help
```

## Kubernetes Deployment

For production deployments using the full stack:

### Prerequisites

- Docker
- Kind (Kubernetes in Docker) or existing K8s cluster
- Task runner (`brew install go-task`)

### Deploy with Task

```bash
# Create kind cluster and deploy all components
task bring-all

# This will:
# 1. Create kind cluster with port mappings
# 2. Build NoETL Docker images
# 3. Deploy PostgreSQL
# 4. Deploy NoETL server and workers
# 5. Deploy observability stack (ClickHouse, Qdrant, NATS)
```

### Verify Deployment

```bash
# Check cluster health
task test-cluster-health

# Access endpoints (permanent NodePort mappings):
# - NoETL API: http://localhost:8082
# - PostgreSQL: localhost:54321
# - ClickHouse: localhost:30123
```

## Component Installation

### Server Only

```bash
# Start server with database initialization
noetl server start --init-db

# Or without init (existing schema)
noetl server start
```

### Workers Only

```bash
# Start worker pool
noetl worker start

# Stop workers
noetl worker stop
```

## Database Setup

NoETL uses PostgreSQL for state management:

```bash
# Initialize database schema
noetl db init

# Validate schema
noetl db validate
```

### Connection Configuration

Set PostgreSQL connection via environment variables:

```bash
export POSTGRES_HOST=localhost
export POSTGRES_PORT=54321
export POSTGRES_USER=demo
export POSTGRES_PASSWORD=demo
export POSTGRES_DB=demo_noetl
```

Or use the default development settings from `docker-compose.yaml`.

## Next Steps

- [Local Development Setup](./local_dev_setup) - Detailed dev environment configuration
- [Docker Usage](./docker_usage) - Container-based development
- [Kind Kubernetes](./kind_kubernetes) - Kubernetes cluster setup
