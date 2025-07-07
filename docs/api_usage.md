# NoETL REST API Guide

This guide provides detailed instructions for using the NoETL REST API.

## Overview

NoETL provides a REST API for managing and executing playbooks. The API is available when running the NoETL server:

```bash
noetl server
```

By default, the API is accessible at `http://localhost:8082`.

## API Endpoints

### Playbook Execution

- `POST /playbook/execute`: Execute a playbook synchronously
- `POST /playbook/execute-async`: Execute a playbook asynchronously

### Catalog Management

- `POST /catalog/register`: Register a playbook in the catalog
- `GET /catalog/list`: View the catalog
- `POST /catalog/upload`: Upload a playbook to the catalog

### Events

- `GET /events/query`: View events
- `POST /events/emit`: Emit an event

## Authentication

Currently, the NoETL API does not require authentication. This may change in future versions.

## Using the API

### Starting the NoETL Server

Before using the API, you need to start the NoETL server:

```bash
noetl server --host 0.0.0.0 --port 8082
```

If the port is already in use, you can force start the server by killing the process using the port:

```bash
noetl server --host 0.0.0.0 --port 8082 --force
```

### Registering a Playbook

Before executing a playbook through the NoETL API, you need to register it in the NoETL catalog:

```bash
curl -X POST "http://localhost:8082/catalog/register" \
  -H "Content-Type: application/json" \
  -d '{
    "content_base64": "'"$(base64 -i ./path/to/playbook.yaml)"'"
  }'
```

### Executing a Playbook Synchronously

To execute a playbook synchronously:

```bash
curl -X POST "http://localhost:8082/playbook/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "path": "workflows/example/playbook",
    "version": "0.1.0",
    "input_payload": {
      "param1": "value1",
      "param2": "value2"
    },
    "sync_to_postgres": true
  }'
```

This will execute the playbook and return the result when the execution is complete.

### Executing a Playbook Asynchronously

To execute a playbook asynchronously:

```bash
curl -X POST "http://localhost:8082/playbook/execute-async" \
  -H "Content-Type: application/json" \
  -d '{
    "path": "workflows/example/playbook",
    "version": "0.1.0",
    "input_payload": {
      "param1": "value1",
      "param2": "value2"
    },
    "sync_to_postgres": true
  }'
```

This will return an event ID that you can use to query the status of the execution.

### Querying Execution Status

To query the status of an execution:

```bash
curl -X GET "http://localhost:8082/events/query?event_id=<event_id>"
```

Replace `<event_id>` with the event ID returned from the asynchronous execution.

### Viewing the Catalog

To view the catalog of registered playbooks:

```bash
curl -X GET "http://localhost:8082/catalog/list"
```

## API Reference

### POST /playbook/execute

Execute a playbook synchronously.

**Request Body:**

```json
{
  "path": "workflows/example/playbook",
  "version": "0.1.0",
  "input_payload": {
    "param1": "value1",
    "param2": "value2"
  },
  "sync_to_postgres": true
}
```

**Parameters:**

- `path` (string, required): Path of the playbook to execute
- `version` (string, optional): Version of the playbook to execute (if omitted, latest version will be used)
- `input_payload` (object, optional): Input payload for the playbook
- `sync_to_postgres` (boolean, optional): Whether to sync execution data to PostgreSQL (default: true)

**Response:**

```json
{
  "status": "success",
  "result": {
    "execution_id": "12345",
    "output": {
      "key1": "value1",
      "key2": "value2"
    }
  }
}
```

### POST /playbook/execute-async

Execute a playbook asynchronously.

**Request Body:**

```json
{
  "path": "workflows/example/playbook",
  "version": "0.1.0",
  "input_payload": {
    "param1": "value1",
    "param2": "value2"
  },
  "sync_to_postgres": true
}
```

**Parameters:**

- `path` (string, required): Path of the playbook to execute
- `version` (string, optional): Version of the playbook to execute (if omitted, latest version will be used)
- `input_payload` (object, optional): Input payload for the playbook
- `sync_to_postgres` (boolean, optional): Whether to sync execution data to PostgreSQL (default: true)

**Response:**

```json
{
  "status": "success",
  "event_id": "12345"
}
```

### POST /catalog/register

Register a playbook in the catalog.

**Request Body:**

```json
{
  "content_base64": "base64_encoded_content"
}
```

**Parameters:**

- `content_base64` (string, required): Base64-encoded content of the playbook YAML file

**Response:**

```json
{
  "status": "success",
  "path": "workflows/example/playbook",
  "version": "0.1.0"
}
```

### GET /catalog/list

View the catalog of registered playbooks.

**Response:**

```json
{
  "status": "success",
  "entries": [
    {
      "resource_path": "workflows/example/playbook1",
      "resource_version": "0.1.0",
      "resource_name": "Example Playbook 1"
    },
    {
      "resource_path": "workflows/example/playbook2",
      "resource_version": "0.2.0",
      "resource_name": "Example Playbook 2"
    }
  ]
}
```

### GET /events/query

Query the status of an execution.

**Query Parameters:**

- `event_id` (string, required): Event ID to query

**Response:**

```json
{
  "status": "success",
  "event": {
    "id": "12345",
    "status": "completed",
    "start_time": "2023-01-01T00:00:00Z",
    "end_time": "2023-01-01T00:01:00Z",
    "result": {
      "key1": "value1",
      "key2": "value2"
    }
  }
}
```

## Next Steps

- [CLI Usage Guide](cli_usage.md) - Learn how to use the NoETL command-line interface
- [Docker Usage Guide](docker_usage.md) - Learn how to use NoETL with Docker
- [Playbook Structure](playbook_structure.md) - Learn how to structure NoETL playbooks