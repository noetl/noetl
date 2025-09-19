# HTTP Plugin

## Overview

The HTTP plugin executes HTTP requests with full template support for dynamic endpoints, headers, parameters, and payloads. It integrates with NoETL's secret management system for secure handling of API tokens and credentials.

## Secret Integration (v0.2+)

Use `{{ secret.* }}` references in headers, params, or payloads to resolve values from external secret managers at runtime. This avoids embedding sensitive data directly in playbook files.

## Examples

### Bearer Token Authentication
```yaml
- step: api_call
  type: http
  method: GET
  endpoint: "https://api.example.com/data"
  headers:
    Authorization: "Bearer {{ secret.api_service_token }}"
    User-Agent: "NoETL/0.2.0"
```

### Basic Authentication
```yaml
- step: basic_auth_call
  type: http
  method: GET
  endpoint: "https://api.example.com/protected"
  headers:
    Authorization: "Basic {{ (secret.username + ':' + secret.password) | b64encode }}"
```

### API Key in Parameters
```yaml
- step: api_with_key
  type: http
  method: GET
  endpoint: "https://api.weather.com/v1/forecast"
  params:
    api_key: "{{ secret.weather_api_key }}"
    location: "{{ city.name }}"
    format: "json"
```

### POST with JSON Payload
```yaml
- step: post_data
  type: http
  method: POST
  endpoint: "https://api.example.com/events"
  headers:
    Authorization: "Bearer {{ secret.api_token }}"
    Content-Type: "application/json"
  data:
    event: "user_action"
    user_id: "{{ workload.user_id }}"
    timestamp: "{{ now() }}"
    metadata: "{{ event_data | tojson }}"
```

### Dynamic Endpoints with Templating
```yaml
- step: user_profile
  type: http
  method: GET
  endpoint: "{{ workload.base_url }}/users/{{ user.id }}/profile"
  headers:
    Authorization: "Bearer {{ secret.user_api_token }}"
  timeout: 30
```

## Supported Authentication Patterns

### OAuth 2.0 Bearer Token
```yaml
headers:
  Authorization: "Bearer {{ secret.oauth_access_token }}"
```

### API Key in Header
```yaml
headers:
  X-API-Key: "{{ secret.service_api_key }}"
```

### Custom Authentication Headers
```yaml
headers:
  X-Auth-Token: "{{ secret.custom_auth_token }}"
  X-Client-ID: "{{ secret.client_identifier }}"
```

## Migration from v0.1.x

### Before (Embedding Secrets)
```yaml
- step: api_call
  type: http
  method: GET
  endpoint: "https://api.example.com/data"
  headers:
    Authorization: "Bearer {{ env.API_TOKEN }}"  # Not secure
```

### After (Secret Management)
```yaml
- step: api_call
  type: http
  method: GET
  endpoint: "https://api.example.com/data"
  headers:
    Authorization: "Bearer {{ secret.api_service_token }}"  # Secure
```

## Advanced Features

### Request Timeout
```yaml
- step: slow_api
  type: http
  method: GET
  endpoint: "https://slow-api.example.com/data"
  timeout: 60  # seconds
```

### Custom User Agent
```yaml
headers:
  User-Agent: "NoETL HTTP Loop Test/1.0"
```

### Multiple Parameters
```yaml
params:
  latitude: "{{ city.lat }}"
  longitude: "{{ city.lon }}"
  units: "metric"
  appid: "{{ secret.weather_api_key }}"
```

## Security Notes

- **Never embed secrets directly** in playbook YAML files
- Use `{{ secret.* }}` references for all sensitive values
- Secrets are resolved at runtime and never persisted to logs or results
- HTTP headers containing secrets are automatically redacted in logs
- Connection details and response data can be logged safely (excluding auth headers)

