# HTTP Plugin

## Overview

The HTTP plugin executes HTTP requests with full template support for dynamic endpoints, headers, parameters, and payloads. It supports multiple configuration styles, integrates with NoETL's secret management system, and provides flexible authentication patterns for REST APIs.

## Configuration Styles

The HTTP plugin supports **three equally valid configuration styles** for specifying request data. Choose the style that best fits your use case.

### 1. Direct Params/Payload (Recommended for Simple Use Cases)

Use `params` for query parameters and `payload` for request body:

```yaml
- step: fetch_weather
  tool: http
  method: GET
  endpoint: "https://api.open-meteo.com/v1/forecast"
  params:
    latitude: "{{ city.lat }}"
    longitude: "{{ city.lon }}"
    current: temperature_2m
```

**When to use:**
- Simple GET requests with query parameters
- Simple POST requests with JSON body
- Clear separation: GET uses `params`, POST uses `payload`
- Most straightforward, readable configuration

### 2. Auto-Routing from Data (Simplest)

Use `data` without explicit `query`/`body` - the system auto-routes based on HTTP method:

```yaml
- step: fetch_data
  tool: http
  method: GET  # Data goes to query params automatically
  endpoint: "https://api.example.com/data"
  data:
    lat: "{{ city.lat }}"
    lon: "{{ city.lon }}"
```

**When to use:**
- Standard REST patterns (GET = query, POST/PUT/PATCH = body)
- Simplest possible configuration
- Don't need mixed query + body

### 3. Unified Data Model (For Complex Use Cases)

Use `data` with explicit `query` and `body` sub-keys for fine-grained control:

```yaml
- step: search_with_filters
  tool: http
  method: POST
  endpoint: "https://api.example.com/search"
  data:
    query:
      page: 1
      limit: 10
    body:
      filters:
        status: active
        category: "{{ category }}"
```

**When to use:**
- Need to send both query params AND body in same request
- Working with mixed GET/POST endpoints
- Want explicit control over where data goes
- Complex nested data structures

## Priority/Fallback Chain

The plugin tries configurations in this order:

### For GET/DELETE Requests (Query Parameters):
1. `data.query` - Explicit query override
2. `data` (auto) - Whole data object as query params
3. `params` - Direct params configuration
4. Nothing - No query parameters

### For POST/PUT/PATCH Requests (Request Body):
1. `data.body` - Explicit body override
2. `data` (auto) - Whole data object as body
3. `payload` - Direct payload configuration
4. Nothing - Empty body

## Secret Integration

Use `{{ secret.* }}` references in headers, params, or payloads to resolve values from external secret managers at runtime.

### Bearer Token Authentication
```yaml
- step: api_call
  tool: http
  method: GET
  endpoint: "https://api.example.com/data"
  headers:
    Authorization: "Bearer {{ secret.api_service_token }}"
```

### API Key in Parameters
```yaml
- step: api_with_key
  tool: http
  method: GET
  endpoint: "https://api.weather.com/v1/forecast"
  params:
    api_key: "{{ secret.weather_api_key }}"
    location: "{{ city.name }}"
```

## Common Patterns

### Pattern: Iterator with HTTP and Save

```yaml
- step: fetch_weather_data
  tool: iterator
  collection: "{{ workload.cities }}"
  element: city
  task:
    tool: http
    method: GET
    endpoint: "https://api.open-meteo.com/v1/forecast"
    params:
      latitude: "{{ city.lat }}"
      longitude: "{{ city.lon }}"
      current: temperature_2m
    save:
      storage: postgres
      table: weather_data
      args:
        city_name: "{{ city.name }}"
        temperature: "{{ result.data.data.current.temperature_2m }}"
        http_status: "{{ result.data.status }}"
```

**Important**: HTTP response structure is nested:
- `result.data.status` - HTTP status code
- `result.data.data` - Response body
- `result.data.headers` - Response headers

## Error Handling

The HTTP plugin validates input and reports errors clearly:

- **Invalid endpoint type**: Raises `ValueError` if endpoint is not a string
- **Invalid data_map type**: Raises `ValueError` if data is not a dict
- **Network errors**: Reported in execution events with full error details
- **Timeout errors**: Reported with timeout duration and request details

All errors are logged and propagated to the execution event system - no silent failures.

## Troubleshooting

### Issue: Query params not being sent

**Solution**: Fixed in v1.1+ - system now properly falls back when `data` is empty.

### Issue: Template not rendering in save block

**Cause**: HTTP response structure is nested - actual data is at `result.data.data`

**Solution**: Use correct template path:
```yaml
# Correct
temperature: "{{ result.data.data.current.temperature_2m }}"
```

## Security Best Practices

- **Never embed secrets directly** in playbook YAML files
- Use `{{ secret.* }}` references for all sensitive values
- HTTP headers containing secrets are automatically redacted in logs
- Store credentials in external secret managers

## See Also

- [Iterator Plugin](iterator.md) - Loop over collections
- [Storage Plugin](storage.md) - Save data to databases
- [Secret Management](../secret_management.md) - Managing credentials
