---
sidebar_position: 2
title: Installation
description: Installation options for NoETL
---

# Installation

NoETL provides multiple installation options across different platforms and package managers.

## Quick Install

Choose your preferred installation method:

### Homebrew (macOS/Linux)

```bash
brew tap noetl/tap
brew install noetl
```

### APT (Ubuntu/Debian)

```bash
echo 'deb [trusted=yes] https://noetl.github.io/apt jammy main' | sudo tee /etc/apt/sources.list.d/noetl.list
sudo apt-get update
sudo apt-get install noetl
```

See [APT Installation Guide](../installation/apt.md) for details.

### PyPI (Python Package)

```bash
pip install noetlctl
```

### Cargo (Rust)

```bash
cargo install noetl
```

### Verify Installation

```bash
noetl --version
noetl --help
```

## Distribution Channels

NoETL is available through multiple distribution channels:

| Channel | Package | Command | Platform |
|---------|---------|---------|----------|
| **Homebrew** | `noetl/tap/noetl` | `brew install noetl/tap/noetl` | macOS, Linux |
| **APT** | `noetl` | `sudo apt-get install noetl` | Ubuntu, Debian |
| **PyPI** | `noetlctl` | `pip install noetlctl` | Cross-platform |
| **Crates.io** | `noetl` | `cargo install noetl` | Cross-platform |
| **GitHub** | Binary | Download from [releases](https://github.com/noetl/noetl/releases) | macOS, Linux |

## Kubernetes Deployment

For production deployments, NoETL runs as a Kubernetes service with PostgreSQL backend.

### Prerequisites

- Docker
- kubectl
- Helm 3.x
- Kind (for local development)

### Local Development with Kind

```bash
# Clone repository
git clone https://github.com/noetl/noetl.git
cd noetl

# Install development tools (auto-detects OS)
noetl run automation/development/setup_tooling.yaml --set action=install-devtools

# Bootstrap complete environment
noetl run boot
```

This creates a Kind cluster with:
- NoETL server and workers (3 replicas)
- PostgreSQL database
- Observability stack (ClickHouse, Qdrant, NATS)

### Development Tools Setup

NoETL provides OS-aware tooling playbooks that automatically install required tools:

```bash
# Detect your operating system
noetl run automation/development/setup_tooling.yaml --set action=detect

# Install all dev tools (macOS uses Homebrew, Linux/WSL2 uses apt-get)
noetl run automation/development/setup_tooling.yaml --set action=install-devtools

# Validate installed tools
noetl run automation/development/setup_tooling.yaml --set action=validate-install
```

**Platform-specific playbooks:**
- **macOS**: `automation/development/tooling_macos.yaml` (uses Homebrew)
- **Linux/WSL2**: `automation/development/tooling_linux.yaml` (uses apt-get)

**Tools installed:** docker, kind, kubectl, helm, jq, yq, pyenv, uv, tfenv, psql

**Optional**: Deploy VictoriaMetrics monitoring stack:

```bash
noetl run automation/infrastructure/monitoring.yaml --set action=deploy
```

### Available Automation Actions

After cloning the repository, use automation playbooks for infrastructure management:

```bash
# Deploy complete environment
noetl run automation/main.yaml bootstrap

# Deploy individual components
noetl run automation/infrastructure/postgres.yaml --set action=deploy
noetl run automation/infrastructure/clickhouse.yaml --set action=deploy
noetl run automation/infrastructure/qdrant.yaml --set action=deploy

# Check status
noetl run automation/infrastructure/postgres.yaml --set action=status

# Remove environment
noetl run automation/main.yaml destroy
```

See [Automation Playbooks](../development/automation_playbooks.md) for complete reference.

### Manual Kubernetes Deployment

For custom deployments without automation:

```bash
# Create namespace
kubectl create namespace noetl

# Deploy PostgreSQL
kubectl apply -f ci/manifests/postgres/

# Deploy NoETL
kubectl apply -f ci/manifests/noetl/
```

## Environment Variables

Key environment variables for configuration:

| Variable | Description | Default |
|----------|-------------|---------|
| `NOETL_SERVER_HOST` | Server bind address | `0.0.0.0` |
| `NOETL_SERVER_PORT` | Server port | `8082` |
| `NOETL_DATABASE_URL` | PostgreSQL connection | Required |
| `NOETL_WORKER_POOL_SIZE` | Worker pool size | `4` |
| `NOETL_LOG_LEVEL` | Logging level | `INFO` |

See [Environment Configuration](/docs/operations/environment_variables) for complete list.

## Verify Installation

### Check Server Status

```bash
curl http://localhost:8082/api/health
```

### List Registered Playbooks

```bash
noetl catalog list playbook --host localhost --port 8082
```

### Run Hello World

```bash
# Local execution
noetl run tests/fixtures/playbooks/hello_world/hello_world.yaml -v

# Distributed execution (after registering playbook)
noetl run tests/fixtures/playbooks/hello_world -r distributed
```

## Next Steps

- [Quick Start](/docs/getting-started/quickstart) - Your first playbook
- [Architecture](/docs/getting-started/architecture) - System components
- [CLI Reference](/docs/reference/noetl_cli_usage) - Command reference
