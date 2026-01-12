---
sidebar_position: 0
title: Overview
description: NoETL command-line tool for development and automation
---

# noetlctl CLI Overview

The `noetlctl` CLI (also called `noetl`) is a Rust-based command-line tool that provides multiple ways to interact with NoETL:

## Core Capabilities

### 1. Local Playbook Execution

Run NoETL playbooks locally without server/worker infrastructure. Supports **auto-discovery** of `noetl.yaml` or `main.yaml` files:

```bash
# Auto-discover playbook and run target
noetl run bootstrap

# Run with auto-discovery (finds ./noetl.yaml or ./main.yaml)
noetl run

# Explicit playbook file
noetl run automation/build.yaml

# Execute specific step/target
noetl run automation/deploy.yaml production

# Auto-discover with variables
noetl run deploy --set env=prod --set version=v2.5 --verbose

# Pass JSON payload (multiple variables)
noetl run bootstrap --payload '{"env":"staging","debug":true}'
```

**Auto-Discovery Priority**:
1. `./noetl.yaml` (priority)
2. `./main.yaml` (fallback)

Perfect for:
- Build automation (replacing Make/Task)
- CI/CD pipelines
- Development scripts
- API testing

[Learn more →](./local_execution.md)

### 2. Process Management

Start and manage NoETL server and worker processes:

```bash
# Start server
noetl server start --init-db

# Start worker
noetl worker start

# Stop services
noetl server stop
noetl worker stop
```

[Learn more →](./architecture.md)

### 3. Resource Management

Register and manage NoETL resources:

```bash
# Register playbook
noetl register playbook --file playbook.yaml

# Register credential
noetl register credential --type postgres --name my_db

# List catalog
noetl catalog list playbooks
```

### 4. Execution Control

Execute and monitor playbooks (distributed mode):

```bash
# Execute playbook
noetl execute playbook my-playbook --json '{"input": "value"}'

# Check status
noetl execute status 12345

# List executions
noetl execute list --limit 10
```

### 5. Development Tools

Kubernetes and database management:

```bash
# Deploy to kind cluster
noetl k8s deploy
noetl k8s redeploy
noetl k8s reset

# Database management
noetl db init
noetl db validate
```

## Installation

Multiple installation options available:

### Package Managers (Recommended)

```bash
# macOS - Homebrew
brew tap noetl/tap
brew install noetl

# Ubuntu/Debian - APT
echo 'deb [trusted=yes] https://noetl.github.io/apt jammy main' | sudo tee /etc/apt/sources.list.d/noetl.list
sudo apt-get update
sudo apt-get install noetl

# Rust - Crates.io
cargo install noetl

# Python - PyPI
pip install noetlctl
```

### Build from Source

```bash
cd crates/noetlctl
cargo build --release

# Binary available at:
# crates/noetlctl/target/release/noetl
```

### Binary Locations

```bash
# After Homebrew install
/opt/homebrew/bin/noetl  # macOS Apple Silicon
/usr/local/bin/noetl     # macOS Intel

# After APT install
/usr/bin/noetl

# After cargo install
~/.cargo/bin/noetl

# After pip install
~/.local/bin/noetl  # Linux
~/Library/Python/3.x/bin/noetl  # macOS
```

**See**: [Installation Guide](../installation/homebrew.md) for complete details.

## Usage Modes

### Local Execution (No Infrastructure)

```bash
# Standalone playbook execution
noetl run automation/tasks.yaml build
```

**Requirements**: None (just the binary)  
**Use Case**: Automation, scripts, CI/CD

### Distributed Execution (Full Infrastructure)

```bash
# Start infrastructure
noetl server start
noetl worker start

# Execute via API
noetl execute playbook my-playbook
```

**Requirements**: PostgreSQL, NATS (optional), ClickHouse (optional)  
**Use Case**: Production workflows, data pipelines

## Command Categories

| Category | Commands | Purpose |
|----------|----------|---------|
| **Local** | `run` | Execute playbooks locally |
| **Server** | `server start/stop` | Manage server process |
| **Worker** | `worker start/stop` | Manage worker process |
| **Register** | `register playbook/credential` | Add resources to catalog |
| **Execute** | `execute playbook/status/list` | Run and monitor workflows |
| **Catalog** | `catalog list` | Query registered resources |
| **K8s** | `k8s deploy/redeploy/remove` | Kubernetes operations |
| **Database** | `db init/validate` | Database management |

## Quick Start Examples

### Build Automation

**File**: [`automation/examples/test_local.yaml`](../../../automation/examples/test_local.yaml)

```yaml
# automation/build.yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: build_tasks

workflow:
  - step: build
    tool:
      kind: shell
      cmds:
        - "cargo build --release"
```

```bash
noetl run automation/build.yaml build
```

### API Testing

**File**: [`automation/examples/http_example.yaml`](../../../automation/examples/http_example.yaml)

```yaml
# automation/api_test.yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: api_tests

workload:
  api_url: "http://localhost:8080"

workflow:
  - step: start
    next:
      - step: health_check
  
  - step: health_check
    tool:
      kind: http
      url: "{{ workload.api_url }}/health"
```

```bash
noetl run automation/api_test.yaml --verbose
```

### Multi-Stage Deployment

**Files**: [`automation/examples/parent_playbook.yaml`](../../../automation/examples/parent_playbook.yaml), [`build_child.yaml`](../../../automation/examples/build_child.yaml), [`deploy_child.yaml`](../../../automation/examples/deploy_child.yaml)

```yaml
# automation/deploy.yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: deployment

workflow:
  - step: build
    tool:
      kind: playbook
      path: ./build.yaml
  
  - step: test
    tool:
      kind: playbook
      path: ./test.yaml
  
  - step: deploy
    tool:
      kind: playbook
      path: ./k8s-deploy.yaml
```

```bash
noetl run automation/deploy.yaml
```

## Available Examples

Complete working examples in `automation/examples/`:

| Example File | Description | Key Features |
|--------------|-------------|--------------|
| [`http_example.yaml`](../../../automation/examples/http_example.yaml) | HTTP GET/POST requests | Query params, result capture, vars extraction |
| [`parent_playbook.yaml`](../../../automation/examples/parent_playbook.yaml) | Playbook composition | Sub-playbook calls, args passing |
| [`build_child.yaml`](../../../automation/examples/build_child.yaml) | Child playbook | Receives args as workload vars |
| [`deploy_child.yaml`](../../../automation/examples/deploy_child.yaml) | Child playbook | Template rendering |
| [`test_local.yaml`](../../../automation/examples/test_local.yaml) | Shell commands | Array/string cmds, target execution |
| [`conditional_flow.yaml`](../../../automation/examples/conditional_flow.yaml) | Conditional routing | case/when/then/else, comparison operators |
| [`unsupported_tools.yaml`](../../../automation/examples/unsupported_tools.yaml) | Tool compatibility | Shows unsupported tool warnings |

**Try them**:
```bash
cd /path/to/noetl
./bin/noetl run automation/examples/http_example.yaml --verbose
./bin/noetl run automation/examples/parent_playbook.yaml --verbose
./bin/noetl run automation/examples/test_local.yaml list_files
./bin/noetl run automation/examples/conditional_flow.yaml --set workload.environment=staging --verbose
./bin/noetl run automation/examples/unsupported_tools.yaml --verbose
```

## Documentation Structure

- **[Architecture & Usage](./architecture.md)** - When to use noetlctl vs Python direct
- **[Local Execution](./local_execution.md)** - Complete guide with detailed examples and file references
- **Command Reference** (coming soon) - Full CLI command documentation
- **Advanced Examples** (coming soon) - Complex automation patterns

## Command Reference

### Run Command

Execute playbooks locally without infrastructure:

```bash
noetl run <PLAYBOOK> [TARGET] [OPTIONS]

# Arguments
<PLAYBOOK>           Path to playbook file (required)
[TARGET]             Step name to start execution from (optional, default: "start")

# Options
--set <KEY=VALUE>    Set individual variables (can be used multiple times)
--payload <JSON>     Pass multiple variables as JSON object
--workload <JSON>    Alias for --payload
--merge              Enable deep merge for payload (default: shallow merge)
--verbose, -v        Show detailed execution output
--help, -h           Display help information
```

**Examples**:

```bash
# Basic execution
noetl run automation/deploy.yaml

# With target
noetl run automation/tasks.yaml cleanup

# Individual variables
noetl run deploy.yaml --set env=prod --set version=v2.5.5

# JSON payload
noetl run deploy.yaml --payload '{"env":"production","debug":true}'

# Combined (--set overrides payload)
noetl run deploy.yaml \
  --payload '{"target":"staging","registry":"gcr.io"}' \
  --set target=production

# Verbose mode
noetl run automation/test.yaml --verbose
```

**Variable Priority** (highest to lowest):
1. `--set` parameters (individual overrides)
2. `--payload` / `--workload` (JSON object)
3. Playbook `workload` section (defaults)

## Get Help

```bash
# General help
noetl --help

# Command-specific help
noetl run --help
noetl server --help
noetl execute --help
```

## Next Steps

- [Learn about local playbook execution with detailed examples](./local_execution.md)
- [Understand architecture patterns](./architecture.md)
- Try examples in `automation/examples/` directory
- View example files: [http_example.yaml](../../../automation/examples/http_example.yaml), [parent_playbook.yaml](../../../automation/examples/parent_playbook.yaml)

