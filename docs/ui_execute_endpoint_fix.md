# UI Execute Endpoint Fix - Issue #97

## Problem

The UI was receiving a 405 Method Not Allowed error when attempting to execute playbooks with payload via the `/api/execute` endpoint.

**Error Details:**
- HTTP Status: 405 Method Not Allowed
- Endpoint: `POST /api/execute`
- Request payload included: `path`, `version`, `input_payload`, `sync_to_postgres`, `merge`

## Root Cause

Two issues were identified:

1. **Missing `/execute` endpoint**: The server only had `/run/{resource_type}` endpoint but not the `/execute` alias that the UI expected
2. **Field name mismatch**: UI was sending `input_payload` but server schema expected `args` or `parameters`

## Solution

### 1. Added `/execute` Endpoint Alias

**File**: `noetl/server/api/run/endpoint.py`

Added a new POST endpoint `/execute` as an alias to the main execution logic:

```python
@router.post("/execute", response_model=ExecutionResponse)
async def execute_playbook_alias(
    request: Request,
    payload: ExecutionRequest
):
    """
    Execute a playbook - Alias endpoint for UI compatibility.
    
    This is an alias for /run/playbook that defaults to playbook execution.
    Accepts the same ExecutionRequest schema.
    """
```

This endpoint:
- Accepts the same `ExecutionRequest` schema as `/run/{resource_type}`
- Returns `ExecutionResponse` with execution_id and status
- Logs requests with "(alias)" tag for debugging
- Captures requestor info (IP, user agent) for audit trails

### 2. Added Backward Compatibility for Input Field Names

**File**: `noetl/server/api/run/schema.py`

Updated `ExecutionRequest` schema to handle legacy field names:

```python
@model_validator(mode='before')
@classmethod
def normalize_input_fields(cls, data):
    """
    Normalize input fields for backward compatibility.
    Handle legacy field names: input_payload -> args
    """
    if isinstance(data, dict):
        # Handle input_payload alias (legacy UI compatibility)
        if 'input_payload' in data and 'args' not in data and 'parameters' not in data:
            data['args'] = data.pop('input_payload')
    return data
```

This normalization:
- Converts `input_payload` → `args` automatically
- Supports `parameters` as an alias (via Field alias)
- Maintains `args` as the canonical field name
- Prioritizes explicit `args` or `parameters` over `input_payload`

## Testing

Validated schema normalization with all field name variants:

```python
# Test 1: input_payload → args
ExecutionRequest(path='test', input_payload={'key': 'value'})
# Result: args={'key': 'value'} ✓

# Test 2: parameters → args (via alias)
ExecutionRequest(path='test', parameters={'key': 'value'})
# Result: args={'key': 'value'} ✓

# Test 3: args directly
ExecutionRequest(path='test', args={'key': 'value'})
# Result: args={'key': 'value'} ✓
```

## API Endpoints

The server now supports three execution endpoints with identical functionality:

1. `POST /api/run/playbook` - Original resource-specific endpoint
2. `POST /api/run/{resource_type}` - Generic resource execution
3. `POST /api/execute` - **NEW** - UI-compatible alias

All endpoints accept:
- `catalog_id` OR `path` + `version` for playbook identification
- `args`, `parameters`, OR `input_payload` for execution parameters
- `merge` boolean for workload merging
- Optional `context` for nested executions

## Backward Compatibility

These changes maintain full backward compatibility:

- Existing CLI and API calls using `args` or `parameters` continue to work
- New UI calls using `input_payload` now work correctly
- All three field names (`args`, `parameters`, `input_payload`) are supported
- No breaking changes to existing integrations

## Related Files

- `/Users/ndrpt/noetl/noetl/noetl/server/api/run/endpoint.py` - Added `/execute` endpoint
- `/Users/ndrpt/noetl/noetl/noetl/server/api/run/schema.py` - Added input field normalization
- `/Users/ndrpt/noetl/noetl/ui-src/src/services/api.ts` - UI service (unchanged, now compatible)
- `/Users/ndrpt/noetl/noetl/ui-src/src/components/Catalog.tsx` - Catalog component (unchanged, now works)

## Next Steps

To test the fix:

1. Rebuild and redeploy the NoETL server:
   ```bash
   task docker-build-noetl
   task deploy-noetl
   ```

2. Verify the endpoint in the UI:
   - Open Catalog page
   - Select a playbook
   - Click "Execute with Payload"
   - Provide JSON payload
   - Execution should start without 405 error

3. Check server logs for confirmation:
   ```bash
   kubectl logs -n noetl-dev deployment/noetl-server --tail=50
   ```
   Look for: `EXECUTE (alias): request:` log entries
