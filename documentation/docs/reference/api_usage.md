---
sidebar_position: 5
title: API Usage
description: NoETL REST API reference and usage guide
---

# API Usage Guide

NoETL exposes a REST API for managing playbooks, credentials, and executions.

## Base URL

- **Local Development**: `http://localhost:8082`
- **Kubernetes**: `http://localhost:8082` (NodePort 30082)

## Authentication

Currently, the API does not require authentication for local development. Production deployments should use a reverse proxy with authentication.

## API Endpoints

### Health Check

```bash
GET /health
```

Returns server health status.

### Catalog API

#### Register Playbook

```bash
POST /api/catalog/playbook
Content-Type: application/json

{
  "content": "<playbook_yaml_content>",
  "path": "examples/my_playbook"
}
```

#### Get Playbook

```bash
GET /api/catalog/playbook/{path}
```

#### List Playbooks

```bash
GET /api/catalog/playbooks
```

### Execution API

#### Execute Playbook

```bash
POST /api/run/playbook
Content-Type: application/json

{
  "path": "examples/my_playbook",
  "payload": {
    "key": "value"
  }
}
```

**Response:**
```json
{
  "execution_id": 12345,
  "status": "started",
  "path": "examples/my_playbook"
}
```

#### Get Execution Status

```bash
GET /api/execution/{execution_id}
```

#### Get Execution Events

```bash
GET /api/events/{execution_id}
```

### Credentials API

#### Register Credential

```bash
POST /api/credentials
Content-Type: application/json

{
  "name": "pg_demo",
  "type": "postgres",
  "description": "Demo PostgreSQL connection",
  "data": {
    "host": "localhost",
    "port": 5432,
    "user": "demo",
    "password": "demo",
    "database": "demo_noetl"
  }
}
```

#### Get Credential (metadata only)

```bash
GET /api/credentials/{name}
```

#### List Credentials

```bash
GET /api/credentials
```

#### Delete Credential

```bash
DELETE /api/credentials/{name}
```

### PostgreSQL Query API

Execute queries directly against the NoETL database:

```bash
POST /api/postgres/execute
Content-Type: application/json

{
  "query": "SELECT * FROM noetl.catalog LIMIT 5",
  "schema": "noetl"
}
```

**Response:**
```json
{
  "status": "ok",
  "result": [{"column": "value"}]
}
```

## Usage Examples

### Register and Execute a Playbook

```bash
# Register playbook
curl -X POST http://localhost:8082/api/catalog/playbook \
  -H "Content-Type: application/json" \
  -d @playbook.json

# Execute playbook
curl -X POST http://localhost:8082/api/run/playbook \
  -H "Content-Type: application/json" \
  -d '{"path": "examples/my_playbook", "payload": {"message": "Hello"}}'

# Check execution status
curl http://localhost:8082/api/execution/12345
```

### Using the CLI (Preferred)

The CLI wraps the API with a convenient interface:

```bash
# Register playbook
noetl register playbook ./my_playbook.yaml

# Execute playbook (distributed mode)
noetl run examples/my_playbook -r distributed --set key=value

# Execute playbook (local mode)
noetl run ./my_playbook.yaml --set key=value

# Check execution
noetl execution status 12345
```

## OpenAPI Documentation

Interactive API documentation is available at:
- Swagger UI: `http://localhost:8082/docs`
- ReDoc: `http://localhost:8082/redoc`

## See Also

- [CLI Reference](/docs/reference/noetl_cli_usage) - Command-line interface
- [Authentication Reference](/docs/reference/auth_and_keychain_reference) - Credential management
