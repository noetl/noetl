# NoETL Command Line Interface (CLI) Guide

This guide provides detailed instructions for using the NoETL command-line interface.

## Overview

NoETL provides a powerful command-line interface for executing playbooks, managing the catalog, and running the server. The main command is `noetl`, which has several subcommands:

- `noetl server` - Start the NoETL server
- `noetl agent` - Execute a playbook directly
- `noetl playbook` - Manage playbooks in the catalog
- `noetl execute` - Execute a playbook from the catalog

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

## Executing Playbooks Directly

You can execute a playbook directly using the `noetl agent` command:

```bash
noetl agent -f ./path/to/playbook.yaml
```

Options:
- `-f, --file`: Path to playbook YAML file (required)
- `--mock`: Run in mock mode
- `-o, --output`: Output format (json or plain)
- `--export`: Export execution data to Parquet file (e.g., ./data/exports/execution_data.parquet)
- `--mlflow`: Use ML model for workflow control (future feature)
- `--pgdb`: Postgres connection string
- `--input`: Path to JSON file with input payload for the playbook
- `--payload`: JSON string with input payload for the playbook
- `--merge`: Whether to merge the input payload with the workload section. Default: False. If omitted, overrides values in the workload with the input payload.
- `--debug`: Debug logging mode

Examples:

```bash
# Basic execution
noetl agent -f ./playbooks/weather_example.yaml

# With debug logging
noetl agent -f ./playbooks/weather_example.yaml --debug

# With payload
noetl agent -f ./playbooks/weather_example.yaml --payload '{"cities": [{"name": "New York", "lat": 40.71, "lon": -74.01}]}'

# With input file
noetl agent -f ./playbooks/weather_example.yaml --input ./data/input/payload.json

# Export execution data
noetl agent -f ./playbooks/weather_example.yaml --export ./data/exports/execution_data.parquet
```

## Managing Playbooks in the Catalog

The `noetl playbook` command allows you to register and execute playbooks in the NoETL catalog:

### Registering a Playbook

```bash
noetl playbook --register ./path/to/playbook.yaml
```

Options:
- `--register, -r`: Path to the playbook YAML file to register
- `--host`: NoETL server host (default: localhost)
- `--port, -p`: NoETL server port (default: 8082)

Example:
```bash
noetl playbook --register ./playbooks/weather_example.yaml --host localhost --port 8082
```

### Executing a Playbook from the Catalog

```bash
noetl playbook --execute --path "workflows/example/playbook"
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
# Execute a playbook by path
noetl playbook --execute --path "workflows/weather/example"

# Execute with a specific version
noetl playbook --execute --path "workflows/weather/example" --version "0.1.0"

# Execute with payload
noetl playbook --execute --path "workflows/weather/example" --payload '{"cities": [{"name": "New York", "lat": 40.71, "lon": -74.01}]}'

# Execute with input file
noetl playbook --execute --path "workflows/weather/example" --input ./data/input/payload.json

# Execute with merge mode
noetl playbook --execute --path "workflows/weather/example" --payload '{"cities": [{"name": "New York", "lat": 40.71, "lon": -74.01}]}' --merge
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
noetl execute path/playbook 1.0.0 --async
```

The event ID is returned when executing a playbook asynchronously. You can view the events in the web interface at:

```
http://localhost:8082/events/query?event_id=<event_id>
```

## Next Steps

- [API Usage Guide](api_usage.md) - Learn how to use the NoETL REST API
- [Playbook Structure](playbook_structure.md) - Learn how to structure NoETL playbooks
- [Workflow Tasks](action_type.md) - Learn about available tasks and their parameters