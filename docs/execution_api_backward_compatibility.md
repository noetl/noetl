# Execution API - Backward Compatibility Guide

## Response Field Compatibility

The unified Execution API maintains backward compatibility by including both old and new field names in responses.

### Field Mapping

| New Field Name | Old Field Name(s) | Value |
|---------------|-------------------|-------|
| `execution_id` | `id` | Same value |
| `type` | `execution_type` | Same value |
| `timestamp` | `start_time` | Same value |

### Response Structure

**Both fields are included in JSON response:**

```json
{
    "execution_id": "exec_123456",
    "id": "exec_123456",              // ← Backward compatible
    
    "type": "playbook",
    "execution_type": "playbook",     // ← Backward compatible
    
    "timestamp": "2025-10-12T10:00:00Z",
    "start_time": "2025-10-12T10:00:00Z",  // ← Backward compatible
    
    "status": "running",
    "path": "examples/weather",
    "version": "v1.0.0",
    "catalog_id": "cat_123",
    "playbook_id": "examples/weather",
    "playbook_name": "weather",
    "progress": 0,
    "result": {...}
}
```

## CLI Compatibility

### Old CLI Code (Still Works)

```python
# CLI looks for either 'id' or 'execution_id'
exec_id = data.get("id") or data.get("execution_id")
```

**Result:** ✅ Works! Both fields are present in response.

### Request Format (Unchanged)

The CLI sends the same format as before:

```json
{
    "playbook_id": "examples/weather",
    "parameters": {"city": "NYC"},
    "merge": false
}
```

**Handling:**
- `playbook_id` is normalized to `path` internally
- `version` defaults to "latest"
- Request is processed through unified schema

## Migration Timeline

### Phase 1: Current (Dual Field Support)
- ✅ Both old and new field names in responses
- ✅ All existing clients work without changes
- ✅ New clients can use either naming convention

### Phase 2: Future (Deprecation)
- ⚠️ Announce deprecation of old field names
- ⚠️ Encourage migration to new field names
- ✅ Continue supporting both for compatibility period

### Phase 3: Future (Removal)
- ❌ Remove deprecated field names
- ✅ Only new field names in responses
- ⚠️ Breaking change for clients not migrated

**Current Status:** Phase 1 (Dual Support)

## Request Compatibility

### Multiple Ways to Specify Target

All these requests are equivalent:

```json
// Method 1: catalog_id (direct lookup)
{
    "catalog_id": "cat_1234567890",
    "parameters": {...}
}

// Method 2: path + version
{
    "path": "examples/weather",
    "version": "v1.0.0",
    "parameters": {...}
}

// Method 3: playbook_id (legacy, normalized to path)
{
    "playbook_id": "examples/weather",
    "parameters": {...}
    // version defaults to "latest"
}
```

### Parameter Field Names

Both names accepted in requests:

```json
// New style
{
    "path": "examples/weather",
    "parameters": {"city": "NYC"}
}

// Old style (still works)
{
    "path": "examples/weather",
    "input_payload": {"city": "NYC"}
}
```

**Pydantic Alias Support:** `populate_by_name=True` allows both.

## Testing Backward Compatibility

### Test Old Response Format

```bash
# Test that CLI still works with old field access
curl -X POST http://localhost:8083/api/executions/run \
  -H "Content-Type: application/json" \
  -d '{"playbook_id": "examples/test", "parameters": {}}' \
  | jq '.id, .execution_id'

# Both should return the same value
```

### Test Old Request Format

```bash
# Old format with playbook_id
curl -X POST http://localhost:8083/api/executions/run \
  -H "Content-Type: application/json" \
  -d '{
    "playbook_id": "examples/test",
    "input_payload": {"key": "value"},
    "merge": false
  }'

# Should work without errors
```

### Test New Request Format

```bash
# New format with path + catalog_id
curl -X POST http://localhost:8083/api/executions/run \
  -H "Content-Type: application/json" \
  -d '{
    "path": "examples/test",
    "version": "v1.0.0",
    "parameters": {"key": "value"},
    "type": "playbook"
  }'

# Should work and return both old/new field names
```

## Error Handling

### Missing Identifier Error

```json
{
    "detail": "At least one identifier must be provided: catalog_id, path, or playbook_id"
}
```

**Fix:** Provide at least one of:
- `catalog_id`
- `path`
- `playbook_id`

### Version Not Found Error

```json
{
    "detail": "Catalog entry 'path' with version 'v1.0.0' not found"
}
```

**Fix:**
- Check version exists in catalog
- Use `version: "latest"` for latest version
- Omit version to default to "latest"

## Validation Rules

### Request Validation

1. **At least one identifier required:**
   - `catalog_id` OR
   - `path` OR
   - `playbook_id`

2. **Version defaults:**
   - If using `path` or `playbook_id`: defaults to "latest"
   - If using `catalog_id`: version from catalog entry

3. **Context merging:**
   - Flat fields (`parent_execution_id`, etc.) merged into `context` object
   - Both formats supported

### Response Population

1. **Execution ID:**
   - `execution_id` = primary value
   - `id` = copy of `execution_id`

2. **Execution Type:**
   - `type` = primary value
   - `execution_type` = copy of `type`

3. **Timestamp:**
   - `timestamp` = primary value
   - `start_time` = copy of `timestamp`

## Best Practices

### For New Clients

```python
# Use new field names
response = api.post("/api/executions/run", json={
    "path": "examples/weather",
    "version": "v1.0.0",
    "parameters": {"city": "NYC"},
    "type": "playbook"
})

execution_id = response.json()["execution_id"]
execution_type = response.json()["type"]
```

### For Existing Clients

```python
# Continue using old field names
response = api.post("/api/executions/run", json={
    "playbook_id": "examples/weather",
    "parameters": {"city": "NYC"}
})

# Both work
exec_id = response.json().get("id") or response.json().get("execution_id")
```

### For Maximum Compatibility

```python
# Support both naming conventions
exec_id = response.json().get("execution_id") or response.json().get("id")
exec_type = response.json().get("type") or response.json().get("execution_type")
start = response.json().get("timestamp") or response.json().get("start_time")
```

## Summary

✅ **Backward Compatible:** Old clients work without changes  
✅ **Forward Compatible:** New clients can use new field names  
✅ **Dual Support:** Both field names in all responses  
✅ **Validated:** Pydantic ensures data consistency  
✅ **Documented:** Clear migration path for future  

The API maintains full backward compatibility while providing a modern, unified interface for new clients.
