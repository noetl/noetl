---
sidebar_position: 1
title: API Integration Examples
description: Examples of integrating with external APIs
---

# API Integration Examples

This section contains examples of integrating NoETL with various external APIs and services.

:::tip Working Examples
Complete integration playbooks are available in the repository:
- [tests/fixtures/playbooks/api_integration/](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/api_integration) - Auth0, webhook handlers
- [tests/fixtures/playbooks/oauth/](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/oauth) - Google Cloud, Interactive Brokers
- [tests/fixtures/playbooks/examples/](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/examples) - HTTP, variables, weather
:::

## Available Integrations

### Authentication & OAuth
- **Auth0**: User authentication with OAuth implicit flow
- **Google OAuth**: Service account and user credential authentication
- **Google Secret Manager**: Secure secrets access with OAuth tokens

### Cloud Storage
- **Google Cloud Storage**: Upload, download, and list objects
- **DuckDB + GCS**: Analytics with cloud storage integration

### Quantum Workloads
- **Quantum Networking Runner**: Bell-state workflow via NVIDIA simulator mode or IBM Runtime API mode

### Data Sources
- **PostgreSQL**: Direct database operations and bulk transfers
- **Snowflake**: Data warehouse queries and cross-platform transfers
- **DuckDB/DuckLake**: In-memory analytics and distributed queries

## Building Your Own Integration

NoETL's HTTP tool makes it easy to integrate with any REST API:

```yaml
- step: call_api
  tool: http
  method: POST
  endpoint: "https://api.example.com/endpoint"
  headers:
    Authorization: "Bearer {{ keychain.api_token }}"
    Content-Type: application/json
  payload:
    data: "{{ workload.data }}"
```

See the [HTTP Tool Reference](/docs/reference/tools/http) for more details.

## Contributing Examples

Have an integration you'd like to share? Open a pull request on [GitHub](https://github.com/noetl/noetl).
