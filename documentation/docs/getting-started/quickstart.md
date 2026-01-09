---
sidebar_position: 1
title: Quick Start
description: Get NoETL running in minutes
---

# Quick Start

Get NoETL running quickly with either PyPI installation or a full local development environment.

## Option 1: PyPI Installation (Simplest)

```bash
# Install NoETL
pip install noetl

# Verify installation
noetl --version
```

## Option 2: Local Development Environment

For a complete environment with server, workers, PostgreSQL, and monitoring:

```bash
# Clone repository
git clone https://github.com/noetl/noetl.git
cd noetl

# Bootstrap: Install tools and provision complete environment
make bootstrap
```

**What bootstrap does:**
1. Installs required tools: Docker, kubectl, helm, kind, task, psql, pyenv, uv, Rust/Cargo
2. Creates Kind Kubernetes cluster
3. Builds NoETL Docker image
4. Deploys PostgreSQL database
5. Deploys observability stack (ClickHouse, Qdrant, NATS JetStream)
6. Deploys monitoring stack (VictoriaMetrics, Grafana, VictoriaLogs)
7. Deploys NoETL server and workers

**Services available after bootstrap:**

| Service | URL | Credentials |
|---------|-----|-------------|
| NoETL Server | http://localhost:8082 | - |
| Grafana | http://localhost:3000 | See `task grafana` |
| VictoriaMetrics | http://localhost:9428 | - |
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
        # Pure Python code - no imports, no def main()
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

After bootstrap, use these common commands:

```bash
# Quick development cycle (rebuild + reload)
task dev

# Deploy all components
task deploy-all

# Check cluster health
task test-cluster-health

# View available tasks
task --list
```

## Register Test Fixtures

NoETL includes example playbooks in `tests/fixtures/playbooks/`:

```bash
# Register test credentials and playbooks
task test:k8s:setup-environment

# Or individually:
task test:k8s:register-credentials
task test:k8s:register-playbooks
```

## Cleanup

```bash
# Destroy environment and clean all resources
make destroy
```

## Next Steps

- [Installation Options](/docs/getting-started/installation) - Detailed setup guide
- [Playbook Structure](/docs/features/playbook_structure) - Learn the DSL syntax
- [CLI Reference](/docs/reference/noetl_cli_usage) - Full command reference
- [Examples](/docs/examples/) - Working playbook examples
