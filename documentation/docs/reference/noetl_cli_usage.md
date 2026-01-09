# NoETL Command Line Interface (CLI) Guide

This guide provides detailed instructions for using the NoETL command-line interface.

## Overview

NoETL provides a powerful command-line interface for executing playbooks, managing the catalog, and running the server. The main command is `noetl`, which has several subcommands:

- `noetl server` - Start the NoETL server
- `noetl worker` - Manage worker processes
- `noetl run playbook` - Execute a playbook (alias: `noetl execute playbook`)
- `noetl db` - Database management commands
- `noetl k8s` - Kubernetes deployment commands
- `noetl build` - Build Docker images

## Quick Start

```bash
# Run a playbook from file
noetl run playbook ./playbooks/my_workflow.yaml

# Run a playbook with payload
noetl run playbook ./playbooks/my_workflow.yaml --payload '{"key": "value"}'

# Start the server
noetl server start

# Start a worker
noetl worker start
```

## Running the NoETL Server

The NoETL server provides a REST API for managing and executing playbooks, as well as a web UI for creating and editing playbooks.

```bash
noetl server
```

Options:
- `--host`: Server host (default: 0.0.0.0)
- `--port`: Server port (default: 8082)
- `--reload`: Enable auto-reload for development (default: False)
- `--force`: Force start the server by killing any process using the port (default: False)

Example:
```bash
noetl server --port 8082 --reload
```

## Executing Playbooks

The primary way to run playbooks is with the `noetl run playbook` command (or its equivalent `noetl execute playbook`):

```bash
noetl run playbook ./path/to/playbook.yaml
```

Options:
- `--payload`: JSON string with input payload for the playbook
- `--input`: Path to JSON file with input payload
- `--merge`: Merge payload with workload section (default: replace)
- `--mock`: Run in mock mode
- `--debug`: Enable debug logging
- `-o, --output`: Output format (json or plain)

Examples:

```bash
# Basic execution
noetl run playbook ./playbooks/data_sync.yaml

# With debug logging
noetl run playbook ./playbooks/data_sync.yaml --debug

# With inline payload
noetl run playbook ./playbooks/data_sync.yaml --payload '{"source": "api", "limit": 100}'

# With payload from file
noetl run playbook ./playbooks/data_sync.yaml --input ./config/payload.json

# Merge payload with workload defaults
noetl run playbook ./playbooks/data_sync.yaml --payload '{"limit": 50}' --merge
```

### Legacy Commands

The following legacy commands are still supported but deprecated:

```bash
# Legacy: Execute directly (use noetl run playbook instead)
noetl agent -f ./path/to/playbook.yaml
```

## Catalog Management

### Registering a Playbook

```bash
noetl playbook register ./path/to/playbook.yaml
```

Options:
- `--register, -r`: Path to the playbook YAML file to register
- `--host`: NoETL server host (default: localhost)
- `--port, -p`: NoETL server port (default: 8082)

Example:
```bash
noetl playbooks --register ./playbooks/weather_loop_example.yaml --host localhost --port 8082
```

### Executing a Playbook from the Catalog

```bash
noetl playbooks --execute --path "workflows/example/playbook"
```

Options:
- `--execute, -e`: Execute a playbook by path
- `--path`: Path of the playbook to execute
- `--version, -v`: Version of the playbook to execute (if omitted, latest version will be used)
- `--input, -i`: Path to JSON file with input payload for the playbook
- `--payload`: JSON string with input payload for the playbook
- `--host`: NoETL server host (default: localhost)
- `--port, -p`: NoETL server port (default: 8082)
- `--sync-to-postgres`: Whether to sync execution data to PostgreSQL (default: true)
- `--merge`: Whether to merge the input payload with the workload section (default: false, which means override)

Examples:

```bash
# Execute a playbooks by path
noetl playbooks --execute --path "workflows/weather/example"

# Execute with a specific version
noetl playbooks --execute --path "workflows/weather/example" --version "1.0.0"

# Execute with payload
noetl playbooks --execute --path "workflows/weather/example" --payload '{"cities": [{"name": "New York", "lat": 40.71, "lon": -74.01}]}'

# Execute with input file
noetl playbooks --execute --path "workflows/weather/example" --input ./data/input/payload.json

# Execute with merge mode
noetl playbooks --execute --path "workflows/weather/example" --payload '{"cities": [{"name": "New York", "lat": 40.71, "lon": -74.01}]}' --merge
```

## Input Payload

You can provide the input payload to the agent in two ways:

1. Using the `--input` option: Provide a path to a JSON file containing the payload.
2. Using the `--payload` option: Provide the JSON payload directly as a string on the command line.

The payload should contain the parameters required by the playbook.

By default, the agent will override the workload section with the input payload if `--merge` is omitted. This means that keys in the input payload will replace the corresponding keys in the workload. 
If you use the `--merge` option, the NoETL agent will merge the input payload with the workload section instead of replacing the keys.

Example payload.json file:

```json
{
  "cities": [
    {
      "name": "New York",
      "lat": 40.71,
      "lon": -74.01
    }
  ],
  "temperature_threshold": 20
}
```

## Monitoring Execution

When executing a playbook asynchronously, you can monitor the execution using the event ID:

```bash
noetl execute path/playbooks 1.0.0 --async
```

The event ID is returned when executing a playbook asynchronously. You can view the events in the web interface at:

```
http://localhost:8082/events/query?event_id=<event_id>
```

## Worker Management

NoETL supports running multiple worker processes for distributed execution of playbooks. Workers run as background processes and can be managed using the `noetl worker` commands.

### Starting Workers

```bash
# Start a worker with default settings
noetl worker start

# Start a worker with custom environment
NOETL_WORKER_POOL_NAME=worker-cpu-01 NOETL_WORKER_POOL_RUNTIME=cpu noetl worker start
```

### Stopping Workers

```bash
# Interactive stop (shows menu if multiple workers running)
noetl worker stop

# Stop specific worker by name
noetl worker stop --name worker-cpu-01

# Force stop without confirmation
noetl worker stop --name worker-gpu-01 --force
```

### Worker Options

- `--name, -n`: Specify worker name for targeted operations
- `--force, -f`: Force stop without confirmation

### Using Make Commands

The Makefile provides convenient commands for worker management:

```bash
# Start worker (uses .env.worker or .env)
make worker-start

# Stop worker(s)
make worker-stop
```

For detailed information about running multiple workers, see [Multiple Workers Guide](multiple_workers.md).

## Next Steps

- [API Usage Guide](api_usage.md) - Learn how to use the NoETL REST API
- [Playbook Structure](playbook_structure.md) - Learn how to structure NoETL playbooks
- [Workflow Tasks](action_type.md) - Learn about available tasks and their parameters