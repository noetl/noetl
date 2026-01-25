# NoETL Command Line Interface (CLI) Guide

This guide provides detailed instructions for using the NoETL command-line interface.

## Overview

NoETL provides a unified command-line interface for executing playbooks with two runtime modes:

- **Local Runtime**: Execute playbooks directly using the Rust interpreter (no server required)
- **Distributed Runtime**: Execute playbooks via NoETL server-worker architecture

The main command is `noetl`, which provides:

- `noetl run` - Execute playbooks (local or distributed)
- `noetl status` - Check execution status
- `noetl cancel` - Cancel running executions
- `noetl context` - Manage execution contexts and runtime preferences
- `noetl server` - Manage NoETL server process
- `noetl worker` - Manage worker processes
- `noetl iap` - Infrastructure as Playbook commands
- `noetl db` - Database management commands
- `noetl k8s` - Kubernetes deployment commands
- `noetl build` - Build Docker images

## Quick Start

```bash
# Run a playbook (auto-detects runtime)
noetl run ./playbooks/my_workflow.yaml

# Run with explicit local runtime
noetl run ./playbooks/my_workflow.yaml -r local

# Run with variables
noetl run ./playbooks/my_workflow.yaml --set key=value --set env=prod

# Run with JSON payload
noetl run ./playbooks/my_workflow.yaml --payload '{"key": "value"}'

# Check execution status
noetl status <execution_id>

# Cancel a running execution
noetl cancel <execution_id> --reason "No longer needed"

# Set context default to local
noetl context set-runtime local

# Start the server (for distributed mode)
noetl server start

# Start a worker (for distributed mode)
noetl worker start
```

## Unified Run Command

The `noetl run` command is the primary way to execute playbooks:

```bash
noetl run <REF> [OPTIONS]
```

### Reference Types

| Format | Example | Default Runtime |
|--------|---------|-----------------|
| File path | `./playbooks/deploy.yaml` | local |
| Catalog URI | `catalog://my-playbook@1.0` | distributed |
| Catalog path | `workflows/etl-pipeline` | distributed |
| Database ID | `pbk_01J...` | distributed |

### Options

| Option | Description |
|--------|-------------|
| `-r, --runtime` | Runtime mode: `local`, `distributed`, or `auto` (default: auto) |
| `-t, --target` | Target step to start from (local runtime only) |
| `--set KEY=VALUE` | Set variables (can be repeated) |
| `--payload JSON` | Pass multiple variables as JSON object |
| `--workload JSON` | Alias for --payload |
| `-V, --version` | Catalog version (for catalog:// refs without @version) |
| `--endpoint` | Server endpoint for distributed runtime |
| `-v, --verbose` | Show detailed execution output |
| `--dry-run` | Validate and show plan without executing |
| `-j, --json` | Emit only JSON response (distributed runtime) |

### Examples

```bash
# Basic execution (auto runtime)
noetl run automation/deploy.yaml

# Force local execution
noetl run automation/deploy.yaml -r local

# Force distributed execution
noetl run catalog://my-playbook@1.0 -r distributed

# With target step
noetl run automation/tasks.yaml -t cleanup

# Individual variables
noetl run deploy.yaml --set env=prod --set version=v2.5.5

# JSON payload
noetl run deploy.yaml --payload '{"env":"production","debug":true}'

# Combined (--set overrides payload)
noetl run deploy.yaml \
  --payload '{"target":"staging","registry":"gcr.io"}' \
  --set target=production

# Verbose mode
noetl run automation/test.yaml -v

# Dry-run mode
noetl run automation/deploy.yaml --dry-run -v
```

## Runtime Resolution

Runtime is determined using this priority:

1. **Explicit flag**: `--runtime local` or `--runtime distributed`
2. **Context config**: From `noetl context set-runtime`
3. **Auto-detect**: Based on reference type (file → local, catalog:// → distributed)

### Setting Context Runtime

```bash
# Set default runtime for current context
noetl context set-runtime local
noetl context set-runtime distributed
noetl context set-runtime auto

# View current context
noetl context current
```

## Context Management

Contexts store server URLs and default runtime preferences:

```bash
# Add a new context
noetl context add local-dev \
  --server-url=http://localhost:8082 \
  --runtime=local \
  --set-current

# Add production context
noetl context add prod \
  --server-url=https://noetl.prod.example.com \
  --runtime=distributed

# List all contexts
noetl context list

# Switch context
noetl context use prod

# View current context
noetl context current

# Change runtime for current context
noetl context set-runtime local

# Delete a context
noetl context delete old-env
```

### Common Context Workflows

**Setup Kind cluster context for registering playbooks/credentials:**
```bash
# Add context for Kind cluster with distributed runtime
noetl context add kind-cluster --server-url http://localhost:8082
noetl context use kind-cluster
noetl context set-runtime distributed

# Now register playbooks and credentials
noetl register playbook tests/fixtures/playbooks/
noetl register credential tests/fixtures/credentials/
```

**Switch between local development and distributed execution:**
```bash
# For local playbook development (no server needed)
noetl context add local-dev --server-url http://localhost:8082
noetl context use local-dev
noetl context set-runtime local
noetl run automation/my_playbook.yaml -v

# For distributed execution (requires Kind cluster running)
noetl context use kind-cluster
noetl context set-runtime distributed
noetl run catalog/path/to/playbook --set env=production
```

**IaP development context (always local):**
```bash
# IaP playbooks always run locally with Rhai scripting
noetl context add iap-gcp --server-url http://localhost:8082
noetl context use iap-gcp
noetl context set-runtime local
noetl iap apply automation/iap/gcp/gke_autopilot.yaml --auto-approve --var action=create
```

## Playbook Executor Section

Playbooks can declare their execution requirements:

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: my_automation
  path: automation/my-task

executor:
  profile: local           # Preferred runtime: local or distributed
  version: noetl-runtime/1 # Runtime version compatibility
  requires:                # Optional: required tools/features
    tools:
      - shell
      - http
    features:
      - templating

workflow:
  - step: start
    tool:
      kind: shell
      cmds:
        - echo "Hello World"
```

## Running the NoETL Server

For distributed execution, start the server:

```bash
noetl server start
```

Options:
- `--init-db`: Initialize database schema on startup

Example:
```bash
noetl server start --init-db
```

Stop the server:
```bash
noetl server stop
noetl server stop --force
```

## Execution Management

### Checking Execution Status

Check the status of a running or completed execution:

```bash
# Basic status check
noetl status <execution_id>

# JSON output
noetl status <execution_id> --json
```

Example output:
```
============================================================
Execution: 543857817971589380
Status:    RUNNING
Steps:     3 completed
Current:   process_data

Completed steps:
  - start
  - fetch_data
  - validate
============================================================
Use --json for full execution details
```

### Cancelling Executions

Cancel a running execution to stop it from processing further:

```bash
# Basic cancellation
noetl cancel <execution_id>

# With a reason
noetl cancel <execution_id> --reason "No longer needed"

# Cascade to child executions (sub-playbooks)
noetl cancel <execution_id> --cascade

# JSON output
noetl cancel <execution_id> --json
```

Options:
- `-r, --reason`: Provide a reason for cancellation (logged in the event)
- `--cascade`: Also cancel child executions spawned by sub-playbook calls
- `-j, --json`: Output JSON response only

Example output:
```
============================================================
Execution: 543857931469455628
Status:    CANCELLED
Cancelled: 1 execution(s)
Message:   Cancelled 1 execution(s)
Reason:    No longer needed
============================================================
```

Use cases:
- **Infinite loops**: Stop runaway workflows that have entered an infinite loop
- **Long-running jobs**: Abort jobs that are no longer needed
- **Hierarchical workflows**: Cancel parent execution and all spawned sub-playbooks

See [Execution Cancellation](../features/execution_cancellation) for detailed documentation.

## Worker Management

Workers execute playbooks in distributed mode:

### Starting Workers

```bash
# Start a worker with default settings
noetl worker start

# Start a worker with custom pool size
noetl worker start --max-workers 4
```

### Stopping Workers

```bash
# Interactive stop (shows menu if multiple workers)
noetl worker stop

# Stop specific worker by name
noetl worker stop --name worker-cpu-01

# Force stop without confirmation
noetl worker stop --name worker-gpu-01 --force
```

## Infrastructure as Playbook (IaP)

Manage cloud infrastructure using playbooks:

```bash
# Initialize state
noetl iap init --project my-gcp-project --bucket my-state-bucket

# Execute infrastructure playbooks
noetl iap apply automation/iap/gcp/gke_autopilot.yaml --auto-approve --var action=create

# Manage state
noetl iap state list
noetl iap state show my-cluster
noetl iap state query "SELECT * FROM resources"

# Sync state
noetl iap sync push
noetl iap sync pull
noetl iap sync status

# Workspace management
noetl iap workspace list
noetl iap workspace create dev-alice
noetl iap workspace switch production
```

## Catalog Management

### Registering Resources

```bash
# Register a playbook
noetl register playbook --file playbook.yaml

# Register from directory
noetl register playbook --directory tests/fixtures/playbooks

# Register credentials
noetl register credential --file credentials/postgres.json
```

### Querying Catalog

```bash
# List playbooks
noetl catalog list Playbook

# List credentials
noetl catalog list Credential --json

# Get specific resource
noetl catalog get my-playbook
```

## Database Management

```bash
# Initialize database schema
noetl db init

# Validate database schema
noetl db validate
```

## Kubernetes Deployment

```bash
# Deploy to kind cluster
noetl k8s deploy

# Rebuild and redeploy
noetl k8s redeploy
noetl k8s redeploy --no-cache

# Reset: rebuild, redeploy, reset schema
noetl k8s reset

# Remove from cluster
noetl k8s remove
```

## Build Commands

```bash
# Build Docker image
noetl build

# Build without cache
noetl build --no-cache

# Build for specific platform
noetl build --platform linux/arm64
```

## Variable Priority

When running playbooks, variables are resolved in this order (highest to lowest):

1. `--set` parameters (individual overrides)
2. `--payload` / `--workload` (JSON object)
3. Playbook `workload` section (defaults)

## Local Runtime Tools

The local runtime supports these tool kinds:

| Tool | Description |
|------|-------------|
| `shell` | Execute shell commands |
| `http` | Make HTTP requests |
| `playbook` | Call sub-playbooks |
| `rhai` | Embedded scripting with Rhai |

## Getting Help

```bash
# General help
noetl --help

# Command-specific help
noetl run --help
noetl context --help
noetl iap --help
noetl server --help
```

## Next Steps

- [Local Execution Guide](/docs/noetlctl/local_execution) - Detailed local runtime documentation
- [Infrastructure as Playbook](/docs/features/infrastructure_as_playbook) - Manage cloud infrastructure
- [Playbook Structure](/docs/features/playbook_structure) - Learn playbook YAML structure
- [API Usage Guide](/docs/reference/api_usage) - REST API documentation
