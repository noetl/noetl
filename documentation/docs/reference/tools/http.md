---
sidebar_position: 1
title: HTTP Tool
description: Make HTTP requests with authentication, pagination, and retry support
---

# HTTP Tool

The HTTP tool executes HTTP requests with support for authentication, pagination, request/response handling, and retry mechanisms.

## Basic Usage

```yaml
- step: fetch_data
  tool: http
  method: GET
  endpoint: "https://api.example.com/data"
  headers:
    Content-Type: application/json
  next:
    - step: process_data
```

## Configuration

### Required Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `endpoint` | string | URL to request (supports Jinja2 templates) |

### Optional Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `method` | string | `GET` | HTTP method: GET, POST, PUT, DELETE, PATCH |
| `headers` | object | `{}` | Request headers |
| `params` | object | `{}` | URL query parameters |
| `payload` | object | `{}` | Request body (JSON) |
| `data` | object | `{}` | Alternative body specification |
| `timeout` | number | `30` | Request timeout in seconds |
| `auth` | object | - | Authentication configuration |

## Authentication

The HTTP tool supports multiple authentication methods via the `auth` block:

### Bearer Token

```yaml
- step: api_call
  tool: http
  method: GET
  endpoint: "https://api.example.com/data"
  auth:
    type: bearer
    credential: my_api_token
```

### Basic Auth

```yaml
- step: api_call
  tool: http
  method: GET
  endpoint: "https://api.example.com/data"
  auth:
    type: basic
    credential: my_credentials
```

### OAuth2

```yaml
- step: api_call
  tool: http
  method: GET
  endpoint: "https://api.example.com/data"
  auth:
    type: oauth2
    credential: my_oauth_config
```

### Custom Headers

```yaml
- step: api_call
  tool: http
  method: GET
  endpoint: "https://api.example.com/data"
  auth:
    type: custom
    headers:
      X-API-Key: "{{ keychain.api_key }}"
```

## Request Body

### JSON Payload

```yaml
- step: create_resource
  tool: http
  method: POST
  endpoint: "https://api.example.com/resources"
  headers:
    Content-Type: application/json
  payload:
    name: "{{ workload.resource_name }}"
    type: "{{ workload.resource_type }}"
```

### Form Data

```yaml
- step: submit_form
  tool: http
  method: POST
  endpoint: "https://api.example.com/form"
  headers:
    Content-Type: application/x-www-form-urlencoded
  data:
    field1: "value1"
    field2: "value2"
```

## Query Parameters

```yaml
- step: search
  tool: http
  method: GET
  endpoint: "https://api.example.com/search"
  params:
    q: "{{ workload.search_term }}"
    page: 1
    limit: 100
```

## Response Handling

The HTTP tool returns a standardized response structure:

```json
{
  "id": "task-uuid",
  "status": "success",
  "data": {
    // Response body (parsed JSON or raw text)
  }
}
```

### Accessing Response Data

```yaml
- step: fetch_users
  tool: http
  method: GET
  endpoint: "https://api.example.com/users"
  vars:
    user_count: "{{ result.data.total }}"
    first_user: "{{ result.data.users[0] }}"
  next:
    - step: process_users
      args:
        users: "{{ fetch_users.data.users }}"
```

## Pagination

For paginated APIs, use the `loop.pagination` block:

```yaml
- step: fetch_all_pages
  tool: http
  method: GET
  endpoint: "https://api.example.com/items"
  params:
    page: 1
    per_page: 100
  loop:
    pagination:
      type: response_based
      continue_while: "{{ response.data.hasMore }}"
      next_page:
        params:
          page: "{{ (response.data.page | int) + 1 }}"
      merge_strategy: append
      merge_path: data.items
      max_iterations: 50
```

See [Pagination Feature](/docs/features/pagination) for detailed pagination patterns.

## Retry Configuration

Configure automatic retries for transient failures:

```yaml
- step: reliable_api_call
  tool: http
  method: GET
  endpoint: "https://api.example.com/data"
  retry:
    max_attempts: 3
    initial_delay: 1.0
    max_delay: 30.0
    backoff_multiplier: 2.0
    retryable_status_codes: [429, 500, 502, 503, 504]
```

See [Retry Mechanism](/docs/features/retry_mechanism) for more details.

## Template Variables

All string values support Jinja2 templating:

```yaml
- step: dynamic_request
  tool: http
  method: "{{ workload.method }}"
  endpoint: "{{ workload.base_url }}/{{ workload.resource }}/{{ vars.resource_id }}"
  headers:
    Authorization: "Bearer {{ keychain.api_token }}"
  params:
    user_id: "{{ vars.user_id }}"
```

### Available Context Variables

| Variable | Description |
|----------|-------------|
| `workload.*` | Global workflow variables |
| `vars.*` | Variables extracted from previous steps |
| `keychain.*` | Resolved credentials from keychain |
| `<step_name>.*` | Results from previous steps |
| `execution_id` | Current execution identifier |

## Examples

### Simple GET Request

```yaml
- step: get_weather
  tool: http
  method: GET
  endpoint: "https://api.weather.com/current"
  params:
    city: "{{ workload.city }}"
    units: metric
```

### POST with Authentication

```yaml
- step: create_ticket
  tool: http
  method: POST
  endpoint: "https://api.support.com/tickets"
  auth:
    type: bearer
    credential: support_api_key
  headers:
    Content-Type: application/json
  payload:
    title: "{{ workload.ticket_title }}"
    description: "{{ workload.description }}"
    priority: high
```

### Chained API Calls

```yaml
workflow:
  - step: start
    next:
      - step: get_user

  - step: get_user
    tool: http
    method: GET
    endpoint: "https://api.example.com/users/{{ workload.user_id }}"
    vars:
      user_email: "{{ result.data.email }}"
    next:
      - step: get_orders

  - step: get_orders
    tool: http
    method: GET
    endpoint: "https://api.example.com/orders"
    params:
      email: "{{ vars.user_email }}"
    next:
      - step: end

  - step: end
```

## Error Handling

The HTTP tool captures errors and returns them in the response:

```json
{
  "id": "task-uuid",
  "status": "error",
  "data": { ... },
  "error": "HTTP 404: Not Found"
}
```

Use conditional routing to handle errors:

```yaml
- step: api_call
  tool: http
  method: GET
  endpoint: "https://api.example.com/data"
  next:
    - when: "{{ api_call.status == 'error' }}"
      then:
        - step: handle_error
    - step: process_success
```

## See Also

- [HTTP Pagination Quick Reference](/docs/reference/dsl/http_pagination_quick_reference)
- [Retry Configuration](/docs/reference/dsl/unified_retry)
- [Authentication & Keychain](/docs/reference/auth_and_keychain_reference)
