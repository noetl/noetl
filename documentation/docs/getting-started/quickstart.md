---
sidebar_position: 1
title: Quick Start
description: Get NoETL running in minutes
---

# Quick Start

Get NoETL running quickly with either PyPI installation or a full local development environment.

## Option 1: PyPI Installation (Simplest)

### Install NoETL Python Package

```bash
# Install NoETL
pip install noetl

# Verify installation
python -c "import noetl; print(noetl.__version__)"
```

### Install NoETL CLI (Rust Binary)

The `noetl` CLI is a fast, native Rust binary for managing NoETL servers, workers, and playbooks:

```bash
# Install via Cargo (Rust package manager)
cargo install noetl

# Verify CLI installation
noetl --version
```

**Prerequisites:**
- Rust toolchain (install from https://rustup.rs/)

**CLI Capabilities:**
- `noetl server start/stop` - Manage NoETL server
- `noetl worker start/stop` - Manage workers
- `noetl db init/validate` - Database management
- `noetl build` - Build Docker images
- `noetl k8s deploy/redeploy/reset` - Kubernetes deployment
- `noetl register playbook` - Register playbooks
- `noetl run playbook` - Execute playbooks

## Option 2: Local Development Environment

For a complete environment with server, workers, PostgreSQL, and observability stack:

```bash
# Clone repository
git clone https://github.com/noetl/noetl.git
cd noetl

# Install NoETL CLI
cargo install --path crates/noetlctl

# Bootstrap entire environment (one command)
noetl run boot
```

**What `noetl run boot` does:**
1. Creates Kind Kubernetes cluster with pre-configured NodePort mappings
2. Builds NoETL Docker images
3. Deploys PostgreSQL database
4. Deploys NoETL server (control plane) and workers (data plane)
5. Initializes database schema
6. Deploys observability stack (ClickHouse, Qdrant, NATS JetStream)
7. Sets up monitoring (if configured)

**Services available after boot:**

| Service | URL | Credentials |
|---------|-----|-------------|
| NoETL Server | http://localhost:8082 | - |
| PostgreSQL | localhost:54321 | demo/demo |
| ClickHouse HTTP | http://localhost:30123 | - |
| Qdrant HTTP | http://localhost:30633 | - |
| NATS Monitoring | http://localhost:30822 | - |

## Your First Playbook

### 1. Create a playbook file

Create `hello_world.yaml`:

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: hello_world
  path: examples/hello_world
workload:
  message: "Hello from NoETL!"
workflow:
  - step: start
    next:
      - step: greet

  - step: greet
    tool:
      kind: python
      libs: {}
      args:
        message: "{{ workload.message }}"
      code: |
        result = {"status": "success", "data": {"greeting": message}}
    next:
      - step: end

  - step: end
```

### 2. Register the playbook

```bash
noetl register playbook hello_world.yaml --host localhost --port 8082
```

### 3. Execute the playbook

```bash
noetl run playbook "examples/hello_world" --host localhost --port 8082
```

### 4. Check the result

```bash
# List executions
curl http://localhost:8082/api/executions | jq

# Get execution details
curl http://localhost:8082/api/executions/1 | jq
```

## Development Workflow

Common development commands:

```bash
# Rebuild and redeploy after code changes
noetl k8s redeploy

# Reset database and redeploy (full reset)
noetl k8s reset

# Re-bootstrap entire environment
noetl run destroy && noetl run boot

# Check deployment status
kubectl get pods -n noetl

# View server logs
kubectl logs -n noetl -l app=noetl-server --tail=100

# View worker logs
kubectl logs -n noetl -l app=noetl-worker --tail=100
```

## Register Test Fixtures

NoETL includes example playbooks in `tests/fixtures/playbooks/`. The CLI supports recursive directory scanning:

```bash
# Register all playbooks from a directory (recursive)
noetl register playbook tests/fixtures/playbooks/ --host localhost --port 8082

# Register all credentials from a directory (recursive)
noetl register credential tests/fixtures/credentials/ --host localhost --port 8082

# Register a single playbook
noetl register playbook tests/fixtures/playbooks/hello_world/hello_world.yaml --host localhost --port 8082

# Register a single credential
noetl register credential tests/fixtures/credentials/pg_k8s.yaml --host localhost --port 8082
```

## Cleanup

```bash
# Destroy entire environment (cluster, deployments, resources)
noetl run destroy
```

## Next Steps

- [Installation Options](/docs/getting-started/installation) - Detailed setup guide
- [Playbook Structure](/docs/features/playbook_structure) - Learn the DSL syntax
- [CLI Reference](/docs/reference/noetl_cli_usage) - Full command reference
- [Examples](/docs/examples/) - Working playbook examples
