# Execution API Schema Documentation

## Overview

The Execution API provides two endpoints for executing playbooks with different lookup strategies. Both endpoints are designed to be MCP (Model Context Protocol) compatible for flexible execution of playbooks, tools, and models.

## Endpoints Comparison

### 1. `/executions/run` - Execute by ID (Legacy/Simple Mode)

**Purpose**: Direct execution using a playbook identifier

**Request Schema**: `ExecutionByIdRequest`
```json
{
  "playbook_id": "tests/fixtures/playbooks/hello_world/hello_world",
  "parameters": {"message": "Hello World"},
  "merge": false,
  "parent_execution_id": "exec_123",
  "parent_event_id": "event_456",
  "parent_step": "fetch_data"
}
```

**Key Characteristics**:
- Uses `playbook_id` for direct catalog lookup
- Simple, flat structure with backward compatibility
- Does not explicitly manage versions (uses whatever version is registered)
- Suitable for quick executions and testing
- Context fields are flattened at the root level

**Response Schema**: `ExecutionStatus`
```json
{
  "id": "exec_789",
  "playbook_id": "tests/fixtures/playbooks/hello_world/hello_world",
  "playbook_name": "hello_world",
  "path": "tests/fixtures/playbooks/hello_world/hello_world",
  "version": "latest",
  "execution_type": "playbook",
  "status": "running",
  "start_time": "2025-10-11T10:30:00Z",
  "progress": 0,
  "result": {...}
}
```

---

### 2. `/execute` - Execute by Path & Version (Version-Controlled Mode)

**Purpose**: Version-controlled execution with path-based catalog lookup

**Request Schema**: `ExecutionByPathRequest`
```json
{
  "path": "tests/fixtures/playbooks/hello_world/hello_world",
  "version": "v1.2.0",
  "execution_type": "playbook",
  "parameters": {"message": "Hello World"},
  "merge": false,
  "sync_to_postgres": true,
  "context": {
    "parent_execution_id": "exec_123",
    "parent_event_id": "event_456",
    "parent_step": "fetch_data"
  },
  "metadata": {
    "triggered_by": "scheduler",
    "priority": "high"
  }
}
```

**Key Characteristics**:
- Uses `path` + `version` for explicit version control
- Supports semantic versioning (e.g., "v1.2.0", "latest")
- MCP-compatible with `execution_type` field
- Structured context object for nested executions
- Additional metadata support for tracking
- Recommended for production environments

**Response Schema**: `ExecutionResponse`
```json
{
  "execution_id": "exec_789",
  "timestamp": "2025-10-11T10:30:00Z",
  "status": "running",
  "path": "tests/fixtures/playbooks/hello_world/hello_world",
  "version": "v1.2.0",
  "execution_type": "playbook",
  "result": null
}
```

---

## Key Differences Summary

| Feature | `/executions/run` | `/execute` |
|---------|-------------------|------------|
| **Lookup Method** | Direct ID | Path + Version |
| **Version Control** | Implicit (latest registered) | Explicit (semantic versioning) |
| **MCP Compatibility** | Limited | Full support |
| **Context Structure** | Flattened | Nested object |
| **Metadata Support** | No | Yes |
| **Use Case** | Quick testing, legacy systems | Production, version management |
| **Response Detail** | Full status | Lightweight response |

---

## MCP Compatibility

The schema is designed to support Model Context Protocol (MCP) execution patterns:

### Supported Execution Types

```python
ExecutionType = Literal["playbook", "tool", "model", "workflow"]
```

1. **playbook**: NoETL playbook execution (current implementation)
2. **tool**: MCP tool execution (future support)
3. **model**: ML model inference (future support)
4. **workflow**: Complex workflow orchestration (future support)

### Extensibility Examples

#### Tool Execution (Future)
```json
{
  "path": "tools/data_validator",
  "version": "v2.0.0",
  "execution_type": "tool",
  "parameters": {
    "tool_name": "data_validator",
    "arguments": {
      "dataset": "customers",
      "rules": ["required_fields", "data_types"]
    }
  }
}
```

#### Model Execution (Future)
```json
{
  "path": "models/sentiment_analysis",
  "version": "v3.1.0",
  "execution_type": "model",
  "parameters": {
    "model_name": "sentiment_bert",
    "inputs": {
      "text": "This product is amazing!"
    },
    "inference_config": {
      "temperature": 0.7,
      "max_tokens": 100
    }
  }
}
```

---

## Schema Architecture

### Request Hierarchy

```
ExecutionRequestBase (common fields)
├── ExecutionByIdRequest (playbook_id)
├── ExecutionByPathRequest (path + version)
├── ToolExecutionRequest (tool_name + arguments)
└── ModelExecutionRequest (model_name + inputs)
```

### Common Fields (All Requests)

- `execution_type`: Type of execution (playbook/tool/model/workflow)
- `parameters`: Input data for execution
- `merge`: Merge with existing workload data
- `sync_to_postgres`: Persist execution state
- `context`: Nested execution context (parent tracking)
- `metadata`: Additional tracking metadata

### Response Models

1. **ExecutionStatus**: Detailed status with progress tracking
   - Used by `/executions/run`
   - Includes full result data
   - Progress percentage
   - Error details

2. **ExecutionResponse**: Lightweight execution acknowledgment
   - Used by `/execute`
   - Minimal response for async executions
   - Check status endpoint for progress

---

## Usage Recommendations

### When to Use `/executions/run`
- Quick testing and development
- Legacy integrations
- Simple one-off executions
- When version control is not critical

### When to Use `/execute`
- Production environments
- Version-controlled deployments
- MCP tool/model integrations
- Complex nested workflows
- When tracking metadata is important
- Multi-tenant environments with isolation

---

## Migration Path

For systems currently using `/executions/run`, migration to `/execute` is straightforward:

**Before (Legacy)**:
```python
{
    "playbook_id": "tests/fixtures/playbooks/hello_world/hello_world",
    "parameters": {"message": "Hello World"}
}
```

**After (Version-Controlled)**:
```python
{
    "path": "tests/fixtures/playbooks/hello_world/hello_world",
    "version": "latest",  # or "v1.0.0"
    "parameters": {"message": "Hello World"}
}
```

---

## Future Extensions

The schema is designed to support:

1. **Batch Execution**: Execute multiple playbooks/tools in one request
2. **Scheduled Execution**: Cron-like scheduling with version pinning
3. **Conditional Execution**: Execution rules and guards
4. **Resource Management**: CPU/memory limits, timeout controls
5. **Cost Tracking**: Execution cost estimation and budgeting
6. **A/B Testing**: Version comparison and performance analysis

---

## See Also

- [Playbook Specification](../../docs/playbook_specification.md)
- [Execution Model](../../docs/execution_model.md)
- [MCP Documentation](https://modelcontextprotocol.io/)
- [API Usage Guide](../../docs/api_usage.md)
