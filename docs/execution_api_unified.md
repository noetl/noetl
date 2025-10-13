# Execution API - Unified Schema & Service Architecture

## Overview

The Execution API has been refactored with a unified request/response schema and service layer separation. Both endpoints (`/executions/run` and `/execute`) now use the same unified schema and business logic.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Client Request                        │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│  Endpoints (endpoint.py)                                 │
│  ┌─────────────────────────────────────────────────┐   │
│  │ POST /executions/run                             │   │
│  │ POST /execute                                    │   │
│  └─────────────────────────────────────────────────┘   │
│             │ Both use ExecutionRequest                  │
└─────────────┼─────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────┐
│  Service Layer (service.py)                              │
│  ┌─────────────────────────────────────────────────┐   │
│  │ ExecutionService                                 │   │
│  │  ├─ resolve_catalog_entry()                     │   │
│  │  ├─ execute()                                    │   │
│  │  └─ persist_workload()                          │   │
│  └─────────────────────────────────────────────────┘   │
│             │                                            │
└─────────────┼───────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────┐
│  Data Layer                                              │
│  ├─ Catalog Table (catalog_id, path, version, content) │
│  ├─ Broker (execute_playbook_via_broker)               │
│  └─ Workload Table (execution tracking)                │
└─────────────────────────────────────────────────────────┘
```

## Unified Schema (schema.py)

### ExecutionRequest

Unified request schema supporting multiple lookup strategies:

```python
{
    # Identifiers (at least one required)
    "catalog_id": "cat_123",           # Direct catalog lookup (priority 1)
    "path": "examples/weather",        # Path-based lookup (priority 2)
    "playbook_id": "examples/weather", # Legacy alias for path (priority 3)
    "version": "v1.0.0",              # Version (default: "latest")
    
    # Execution configuration
    "type": "playbook",                # playbook, tool, model, workflow
    "parameters": {...},               # Input data
    "merge": false,                    # Merge with existing workload
    "sync_to_postgres": true,          # Persist state
    
    # Context (nested or flat)
    "context": {
        "parent_execution_id": "exec_456",
        "parent_event_id": "event_789",
        "parent_step": "step_name"
    },
    # OR flat fields for backward compatibility
    "parent_execution_id": "exec_456",
    "parent_event_id": "event_789",
    "parent_step": "step_name",
    
    # Additional metadata
    "metadata": {...}
}
```

**Validation & Normalization:**
- At least one identifier must be provided
- `playbook_id` is normalized to `path` internally
- `version` defaults to "latest" for path-based lookups
- Flat context fields are merged into `context` object

### ExecutionResponse

Unified response schema:

```python
{
    "execution_id": "exec_123",        # Unique execution ID
    "catalog_id": "cat_456",           # Resolved catalog ID
    "path": "examples/weather",        # Resolved path
    "playbook_id": "examples/weather", # For backward compatibility
    "playbook_name": "weather",        # Derived from path
    "version": "v1.0.0",              # Resolved version
    "type": "playbook",                # Execution type
    "status": "running",               # Current status
    "timestamp": "2025-10-12T...",    # Start time
    "end_time": null,                  # Completion time
    "progress": 0,                     # Progress (0-100)
    "result": {...},                   # Result data (or null)
    "error": null                      # Error message if failed
}
```

**Aliases:**
- `execution_id` can be accessed as `id`
- `type` can be accessed as `execution_type`
- `timestamp` can be accessed as `start_time`
- `parameters` can be accessed as `input_payload`

## Service Layer (service.py)

### ExecutionService

**Methods:**

1. **`resolve_catalog_entry(request)`**
   - Resolves catalog entry using priority-based lookup
   - Returns: `(path, version, content, catalog_id)`
   - Lookup order:
     1. `catalog_id` → Direct catalog table lookup
     2. `path` + `version` → Path with explicit version
     3. `path` + "latest" → Latest version for path

2. **`execute(request)`**
   - Orchestrates complete execution flow
   - Resolves catalog entry
   - Executes via broker
   - Persists workload data
   - Returns ExecutionResponse

3. **`persist_workload(execution_id, parameters)`**
   - Persists execution parameters to workload table
   - Non-blocking (logs warnings on failure)

## Endpoints (endpoint.py)

### POST /executions/run

**Purpose:** Primary execution endpoint with unified schema

**Request:** `ExecutionRequest`

**Response:** `ExecutionResponse`

**Example:**
```bash
curl -X POST http://localhost:8083/api/executions/run \
  -H "Content-Type: application/json" \
  -d '{
    "path": "examples/weather/forecast",
    "version": "v1.0.0",
    "parameters": {"city": "New York"},
    "type": "playbook"
  }'
```

### POST /execute

**Purpose:** Alias endpoint (identical functionality to /executions/run)

**Request:** `ExecutionRequest`

**Response:** `ExecutionResponse`

**Example:**
```bash
curl -X POST http://localhost:8083/api/execute \
  -H "Content-Type: application/json" \
  -d '{
    "catalog_id": "cat_1234567890",
    "parameters": {"city": "New York"}
  }'
```

## Catalog Lookup Strategies

### Strategy 1: catalog_id (Highest Priority)

```python
{
    "catalog_id": "cat_1234567890",
    "parameters": {...}
}
```

**Query:**
```sql
SELECT catalog_id, path, version, content
FROM noetl.catalog
WHERE catalog_id = 'cat_1234567890'
```

### Strategy 2: path + version

```python
{
    "path": "examples/weather/forecast",
    "version": "v1.0.0",
    "parameters": {...}
}
```

**Query:**
```sql
SELECT catalog_id, content
FROM noetl.catalog
WHERE path = 'examples/weather/forecast' AND version = 'v1.0.0'
```

### Strategy 3: path + "latest"

```python
{
    "path": "examples/weather/forecast",
    # version defaults to "latest"
    "parameters": {...}
}
```

**Query:**
```sql
SELECT catalog_id, version, content
FROM noetl.catalog
WHERE path = 'examples/weather/forecast'
ORDER BY created_at DESC
LIMIT 1
```

### Strategy 4: playbook_id (Legacy)

```python
{
    "playbook_id": "examples/weather/forecast",
    "parameters": {...}
}
```

**Normalized to:** `path = "examples/weather/forecast"`, `version = "latest"`

## MCP Compatibility

### Playbook Execution

```python
{
    "path": "playbooks/data_pipeline",
    "version": "v2.1.0",
    "type": "playbook",
    "parameters": {...}
}
```

### Tool Execution (Future)

```python
{
    "tool_name": "data_validator",
    "type": "tool",
    "arguments": {...}
}
```

Normalized to:
```python
{
    "path": "tools/data_validator",
    "type": "tool",
    "parameters": {...}
}
```

### Model Execution (Future)

```python
{
    "model_name": "sentiment_analysis",
    "type": "model",
    "inputs": {...},
    "inference_config": {...}
}
```

Normalized to:
```python
{
    "path": "models/sentiment_analysis",
    "type": "model",
    "parameters": {...},
    "metadata": {"inference_config": {...}}
}
```

## Migration Guide

### Old API (Before Unification)

**Endpoint 1:** `/executions/run`
```python
{
    "playbook_id": "examples/weather/forecast",
    "parameters": {"city": "NYC"},
    "merge": false,
    "parent_execution_id": "exec_123"
}
```

**Endpoint 2:** `/execute`
```python
{
    "path": "examples/weather/forecast",
    "version": "v1.0.0",
    "input_payload": {"city": "NYC"},
    "merge": false,
    "sync_to_postgres": true
}
```

### New API (After Unification)

**Both endpoints now accept the same unified request:**

```python
{
    # Use any identifier strategy
    "catalog_id": "cat_123",  # OR
    "path": "examples/weather/forecast",
    "version": "v1.0.0",      # OR
    "playbook_id": "examples/weather/forecast",
    
    # Flexible field names (aliases supported)
    "parameters": {"city": "NYC"},    # OR "input_payload"
    "type": "playbook",               # OR "execution_type"
    
    # Context can be nested or flat
    "context": {
        "parent_execution_id": "exec_123"
    },
    # OR
    "parent_execution_id": "exec_123",
    
    "merge": false,
    "sync_to_postgres": true
}
```

## Benefits

✅ **Unified Interface**: Both endpoints use the same schema and logic  
✅ **Multiple Lookup Strategies**: catalog_id, path+version, or playbook_id  
✅ **Backward Compatible**: Supports legacy field names via aliases  
✅ **Service Layer Separation**: Business logic isolated from routing  
✅ **MCP Ready**: Extensible for tool/model execution  
✅ **Discoverable**: catalog_id enables direct entry lookup  
✅ **Version Control**: Explicit version management with path-based lookup  
✅ **Flexible Context**: Supports both nested and flat context fields  

## Error Handling

### Validation Errors (400)

- No identifier provided
- Invalid execution type
- Missing required fields

### Not Found Errors (404)

- Catalog entry not found
- No versions available for path
- Specific version not found

### Server Errors (500)

- Database connection issues
- Broker execution failures
- Workload persistence failures (non-blocking, logged)

## See Also

- [Execution API Schema Documentation](../../docs/execution_api_schema.md)
- [Playbook Specification](../../docs/playbook_specification.md)
- [Catalog API Documentation](../../docs/catalog_api.md)
- [MCP Documentation](https://modelcontextprotocol.io/)
