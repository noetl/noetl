---
sidebar_position: 8
title: Script Attribute
description: Load external scripts from cloud storage or file system
---

# Script Attribute

The script attribute enables loading code from external sources (GCS, S3, file, HTTP) similar to Azure Data Factory's linked services.

## Overview

All action tools support the `script` attribute for external code execution:

```yaml
- step: run_external_script
  tool: python
  script:
    uri: gs://my-bucket/scripts/transform.py
    source:
      type: gcs
      auth: gcp_service_account
```

## Priority Order

When multiple code sources are specified:
1. `script` (highest priority)
2. `code_b64` / `command_b64`
3. `code` / `command` (inline)

## Source Types

### Google Cloud Storage (GCS)

```yaml
script:
  uri: gs://bucket-name/path/to/script.py
  source:
    type: gcs
    auth: gcp_credential  # Registered credential reference
```

### Amazon S3

```yaml
script:
  uri: s3://bucket-name/path/to/script.sql
  source:
    type: s3
    region: us-west-2
    auth: aws_credentials
```

### Local File

```yaml
script:
  uri: ./scripts/transform.py
  source:
    type: file
```

Or absolute path:

```yaml
script:
  uri: /opt/noetl/scripts/transform.py
  source:
    type: file
```

### HTTP

```yaml
script:
  uri: transform.py
  source:
    type: http
    endpoint: https://api.example.com/scripts
    method: GET
    headers:
      Authorization: "Bearer {{ secret.api_token }}"
    timeout: 30
```

## Supported Tools

The script attribute works with:
- `python` - Python scripts
- `postgres` - SQL scripts
- `duckdb` - DuckDB queries
- `snowflake` - Snowflake SQL
- `http` - Request templates

## Examples

### Python with GCS

```yaml
- step: transform_data
  tool: python
  script:
    uri: gs://data-pipelines/scripts/transform.py
    source:
      type: gcs
      auth: gcp_service_account
  args:
    input_data: "{{ previous_step.data }}"
```

### PostgreSQL Migration from S3

```yaml
- step: run_migration
  tool: postgres
  auth: pg_prod
  script:
    uri: s3://sql-scripts/migrations/v2.5/upgrade.sql
    source:
      type: s3
      region: us-west-2
      auth: aws_credentials
```

### DuckDB Query from HTTP

```yaml
- step: run_analytics
  tool: duckdb
  script:
    uri: analytics/daily_summary.sql
    source:
      type: http
      endpoint: https://queries.internal.company.com
      headers:
        X-API-Key: "{{ secret.internal_api_key }}"
```

## Working Examples

Complete script execution playbooks:
- [script_execution/](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/script_execution)

## Related

- [Python Tool](../reference/tools/python) - Inline Python execution
- [PostgreSQL Tool](../reference/tools/postgres) - Database operations
- [GCS Tool](../reference/tools/gcs) - Cloud storage uploads
