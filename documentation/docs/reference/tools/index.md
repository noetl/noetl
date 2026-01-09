---
sidebar_position: 0
title: Tools Overview
description: Overview of all available NoETL action tools
---

# NoETL Tools Reference

NoETL provides a set of action tools that execute specific tasks within workflows. Each tool is designed for a particular type of operation, from HTTP requests to database queries to container execution.

## Available Tools

| Tool | Description | Use Case |
|------|-------------|----------|
| [HTTP](/docs/reference/tools/http) | Make HTTP/REST API requests | API integrations, webhooks |
| [PostgreSQL](/docs/reference/tools/postgres) | Execute PostgreSQL queries | OLTP databases, data storage |
| [Python](/docs/reference/tools/python) | Run Python code | Data transformation, custom logic |
| [DuckDB](/docs/reference/tools/duckdb) | Analytics with DuckDB | Data analysis, ETL, cloud storage |
| [Snowflake](/docs/reference/tools/snowflake) | Query Snowflake data warehouse | Data warehouse operations |
| [Container](/docs/reference/tools/container) | Run scripts in Kubernetes | Complex workloads, custom environments |
| [GCS](/docs/reference/tools/gcs) | Upload files to Google Cloud Storage | File storage, data export |
| [DuckLake](/docs/reference/tools/ducklake) | Lakehouse queries | Unified analytics |

## Tool Selection Guide

### API & Web Operations

- **HTTP**: REST API calls, webhooks, external service integration
- **GCS**: Cloud storage file uploads

### Database Operations

- **PostgreSQL**: Transactional workloads, application databases
- **Snowflake**: Data warehouse queries, analytics at scale
- **DuckDB**: Local analytics, cloud storage queries, cross-source joins
- **DuckLake**: Lakehouse architecture, unified data access

### Code Execution

- **Python**: Data transformation, custom logic, simple scripts
- **Container**: Complex dependencies, isolated environments, GPU workloads

## Common Patterns

### Basic Tool Usage

```yaml
- step: my_step
  tool: http
  method: GET
  endpoint: "https://api.example.com/data"
```

### With Authentication

```yaml
- step: secure_query
  tool: postgres
  auth:
    type: postgres
    credential: production_db
  query: "SELECT * FROM users"
```

### With Variable Extraction

```yaml
- step: fetch_data
  tool: http
  method: GET
  endpoint: "https://api.example.com/users"
  vars:
    user_count: "{{ result.data.total }}"
    first_user: "{{ result.data.users[0] }}"
```

### With External Script

```yaml
- step: run_script
  tool: python
  script:
    uri: gs://scripts/transform.py
    source:
      type: gcs
      auth: gcp_service_account
```

## Authentication

All tools support the unified authentication system:

```yaml
auth:
  type: <service_type>    # postgres, snowflake, gcs, s3, http, etc.
  credential: <name>      # Reference to registered credential
```

See [Authentication Reference](/docs/reference/auth_and_keychain_reference) for details.

## Response Format

All tools return a standardized response structure:

```json
{
  "id": "task-uuid",
  "status": "success",
  "data": {
    // Tool-specific result data
  }
}
```

On error:

```json
{
  "id": "task-uuid",
  "status": "error",
  "error": "Error message",
  "data": {}
}
```

## Template Support

All tools support Jinja2 templating in string values:

```yaml
- step: dynamic_request
  tool: http
  endpoint: "{{ workload.base_url }}/{{ vars.resource_id }}"
  headers:
    Authorization: "Bearer {{ keychain.api_token }}"
```

### Available Context Variables

| Variable | Description |
|----------|-------------|
| `workload.*` | Global workflow variables |
| `vars.*` | Variables from previous steps |
| `keychain.*` | Resolved credentials |
| `<step_name>.*` | Results from specific steps |
| `execution_id` | Current execution ID |

## See Also

- [DSL Specification](/docs/reference/dsl_spec) - Complete playbook syntax
- [Authentication](/docs/reference/auth_and_keychain_reference) - Credential management
- [Retry Configuration](/docs/reference/unified_retry) - Error handling
