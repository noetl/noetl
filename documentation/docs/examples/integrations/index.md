---
sidebar_position: 1
title: API Integration Examples
description: Examples of integrating with external APIs
---

# API Integration Examples

This section contains examples of integrating NoETL with various external APIs and services.

## Coming Soon

- **Slack Integration**: Send notifications to Slack channels
- **GitHub API**: Automate repository workflows
- **Salesforce**: Sync data with Salesforce CRM
- **AWS Services**: Integration with Lambda, S3, and more

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

Have an integration you'd like to share? See our [contribution guide](/docs/development/development) for how to add examples.
