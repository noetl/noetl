# NoETL Runtime API Refactoring - Complete

**Status**: ✅ Complete and tested  
**Date**: October 12, 2025

## Summary

Successfully refactored `runtime.py` from a monolithic file into a structured package with separate endpoint, schema, and service modules following the same pattern as the execution module.

## Module Structure

```
noetl/api/routers/runtime/
├── __init__.py       # Package exports (router, schemas, service)
├── endpoint.py       # FastAPI routing layer
├── schema.py         # Pydantic request/response models
└── service.py        # Business logic layer
```

## Endpoints

### Worker Pool Management
- **POST /api/worker/pool/register** - Register or update a worker pool
- **DELETE /api/worker/pool/deregister** - Deregister a worker pool (mark offline)
- **POST /api/worker/pool/deregister** - POST alternative for deregistration (backward compatible)
- **POST /api/worker/pool/heartbeat** - Send heartbeat with auto-recreation support
- **GET /api/worker/pools** - List all worker pools with optional filters

### Generic Runtime Components
- **POST /api/runtime/register** - Register any runtime component (server_api, broker, etc.)
- **DELETE /api/runtime/deregister** - Deregister a runtime component

### Broker Management (Placeholder)
- **POST /api/broker/register** - Register broker (placeholder)
- **POST /api/broker/heartbeat** - Broker heartbeat (placeholder)
- **GET /api/brokers** - List brokers (placeholder)
- **DELETE /api/broker/deregister** - Deregister broker (placeholder)

## Schema Design

### RuntimeRegistrationRequest
Unified registration schema for all runtime components:

**Fields**:
- `name` (required): Component name
- `kind` (default: "worker_pool"): Component type (worker_pool, broker, server_api, etc.)
- `runtime` (optional): Runtime type (python, nodejs, etc.)
- `uri` (optional, required for server_api/broker): Base URL
- `status` (default: "ready"): Component status
- `capacity` (optional): Maximum capacity
- `labels` (optional): Arbitrary labels
- `pid`, `hostname`, `meta` (optional): Additional metadata

**Field Aliases**:
- `component_type` ↔ `kind`
- `base_url` ↔ `uri`

**Validation**:
- All string fields automatically stripped
- Status automatically lowercased
- URI required validation for server_api and broker components

**Example**:
```json
{
  "name": "worker-pool-01",
  "kind": "worker_pool",
  "runtime": "python",
  "status": "ready",
  "capacity": 10,
  "labels": {"env": "prod"},
  "pid": 12345,
  "hostname": "worker-node-1"
}
```

### WorkerPoolRegistrationRequest
Specialized subclass with `kind` fixed to "worker_pool".

### RuntimeRegistrationResponse
Response after registration:

**Fields**:
- `status`: Registration status (ok, recreated, error)
- `name`: Component name
- `runtime_id`: Unique runtime ID (string)
- `kind`: Component type
- `runtime`: Runtime type

**Example**:
```json
{
  "status": "ok",
  "name": "worker-pool-01",
  "runtime_id": "123456789",
  "kind": "worker_pool",
  "runtime": "python"
}
```

### RuntimeHeartbeatRequest
Minimal heartbeat request:

**Fields**:
- `name` (optional): Component name (can also be set via NOETL_WORKER_POOL_NAME env var)
- `registration` (optional): Registration data for auto-recreation

### RuntimeHeartbeatResponse
Heartbeat response:

**Fields**:
- `status`: ok, unknown, recreated
- `name`: Component name
- `runtime_id`: Runtime ID if known
- `runtime`: Runtime type (only for recreated)

**Status Codes**:
- `200 OK` with `status: "ok"`: Heartbeat accepted
- `404 Not Found` with `status: "unknown"`: Component not registered, re-registration required
- `200 OK` with `status: "recreated"`: Component auto-recreated from registration data

### RuntimeComponentInfo
Component information for listings:

**Fields**:
- `name`: Component name
- `runtime`: Runtime metadata (JSON)
- `status`: Current status
- `capacity`: Maximum capacity
- `labels`: Component labels
- `heartbeat`: Last heartbeat timestamp (ISO 8601)
- `created_at`: Creation timestamp
- `updated_at`: Last update timestamp

### RuntimeListResponse
List response with filters:

**Fields**:
- `items`: List of RuntimeComponentInfo
- `count`: Total number of components
- `runtime`: Filter applied (runtime type)
- `status`: Filter applied (status)
- `error`: Error message if query failed

## Service Layer

### RuntimeService

**Methods**:

#### register_component()
Register or update a runtime component with validation and database persistence.

**Logic**:
1. Validate URI requirements (required for server_api/broker)
2. Generate snowflake ID
3. Prepare runtime metadata JSON
4. Upsert to database (ON CONFLICT DO UPDATE)
5. Return response with runtime_id

**Error Handling**:
- Captures database errors outside async context manager
- Raises HTTPException with appropriate status codes
- Handles commit warnings gracefully

#### deregister_component()
Mark component as offline in the database.

#### process_heartbeat()
Process heartbeat with auto-recreation support.

**Logic**:
1. Get component name from request or environment
2. Try to update heartbeat timestamp in database
3. If not found and auto_recreate_runtime=True:
   - Attempt to recreate from registration data
   - Return status="recreated" if successful
4. If not found and auto-recreation disabled/failed:
   - Raise 404 with Retry-After header

**Auto-Recreation**:
Controlled by settings:
- `auto_recreate_runtime`: Enable/disable feature
- `heartbeat_retry_after`: Retry-After header value (seconds)

#### _upsert_worker_pool()
Internal helper for worker pool upsert during heartbeat auto-recreation.

#### list_components()
Query runtime components with optional filters:
- `kind`: Component type filter
- `runtime`: Runtime type filter (matches runtime.type JSON field)
- `status`: Status filter

Returns RuntimeListResponse with items and count.

## Key Implementation Patterns

### 1. Async Context Manager Safety
Never raise exceptions inside `async with get_async_db_connection()` blocks:

```python
row = None
db_error = None

try:
    async with get_async_db_connection() as conn:
        # Database operations
        row = await cursor.fetchone()
except Exception as e:
    db_error = e

# Check results after context manager exits
if db_error:
    raise HTTPException(...)
```

### 2. String ID Coercion
All ID fields use field validators to coerce integers to strings:

```python
@field_validator('runtime_id', mode='before')
@classmethod
def coerce_to_string(cls, v):
    if v is None:
        return v
    return str(v)
```

### 3. Field Aliases
Support both old and new field names:

```python
kind: RuntimeKind = Field(
    default="worker_pool",
    alias="component_type"
)

model_config = {
    "populate_by_name": True,
}
```

### 4. Service Layer Separation
Endpoints are thin wrappers that call service methods:

```python
@router.post("/worker/pool/register")
async def register_worker_pool(request: WorkerPoolRegistrationRequest):
    try:
        return await RuntimeService.register_component(request)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

## Migration from Old Structure

### Before
```python
# noetl/api/routers/runtime.py (monolithic file)
@router.post("/worker/pool/register")
async def register_worker_pool(request: Request):
    body = await request.json()
    # Validation and DB logic mixed together
    ...
```

### After
```python
# noetl/api/routers/runtime/endpoint.py
@router.post("/worker/pool/register")
async def register_worker_pool(request: WorkerPoolRegistrationRequest):
    return await RuntimeService.register_component(request)

# noetl/api/routers/runtime/service.py
class RuntimeService:
    @staticmethod
    async def register_component(request: RuntimeRegistrationRequest):
        # Business logic
        ...

# noetl/api/routers/runtime/schema.py
class WorkerPoolRegistrationRequest(RuntimeRegistrationRequest):
    # Pydantic validation
    ...
```

## Testing

### Manual Tests Conducted

1. **Worker Pool Registration**:
```bash
curl -X POST http://localhost:8083/api/worker/pool/register \
  -H "Content-Type: application/json" \
  -d '{"name": "test-pool", "runtime": "python", "capacity": 10}'
```
✅ Returns registration response with runtime_id

2. **Worker Pool Heartbeat**:
```bash
curl -X POST http://localhost:8083/api/worker/pool/heartbeat \
  -H "Content-Type: application/json" \
  -d '{"name": "test-pool"}'
```
✅ Returns heartbeat response with status="ok"

3. **List Worker Pools**:
```bash
curl "http://localhost:8083/api/worker/pools?runtime=python&status=ready"
```
✅ Returns list of worker pools with filters applied

4. **Worker Pool Deregistration**:
```bash
curl -X DELETE http://localhost:8083/api/worker/pool/deregister \
  -H "Content-Type: application/json" \
  -d '{"name": "test-pool"}'
```
✅ Returns deregistration confirmation

### Test Results

All endpoints functional:
- ✅ Registration with validation working
- ✅ Deregistration (both DELETE and POST) working
- ✅ Heartbeat with database updates working
- ✅ Listing with filters working
- ✅ Field aliases working (component_type/kind, base_url/uri)
- ✅ String validation and normalization working
- ✅ Async context manager safety pattern working
- ✅ String serialization for all ID fields working (runtime_id, catalog_id, etc.)

## Backward Compatibility

✅ All existing endpoints maintained  
✅ Field aliases support old field names  
✅ POST alternative for DELETE operations preserved  
✅ Environment variable fallback for worker names maintained  
✅ Auto-recreation feature preserved  

## Files Modified

**Created**:
- `noetl/api/routers/runtime/__init__.py`
- `noetl/api/routers/runtime/endpoint.py`
- `noetl/api/routers/runtime/schema.py`
- `noetl/api/routers/runtime/service.py`

**Removed**:
- `noetl/api/routers/runtime.py` (backed up to runtime.py.bak)

**Unchanged**:
- `noetl/api/routers/__init__.py` (import statement already compatible with package structure)

## Documentation

- `docs/runtime_api_refactoring.md` - This document

## Benefits of Refactoring

1. **Separation of Concerns**: Routing, validation, and business logic clearly separated
2. **Testability**: Service methods can be unit tested independently
3. **Maintainability**: Easier to locate and modify specific functionality
4. **Type Safety**: Pydantic models provide strong typing and validation
5. **Consistency**: Follows same pattern as execution module
6. **Extensibility**: Easy to add new component types or endpoints
7. **Documentation**: Self-documenting through Pydantic schemas and docstrings

## Future Enhancements

1. **Broker Implementation**: Replace placeholder endpoints with full broker management
2. **Component Health Checks**: Add health check endpoints beyond heartbeat
3. **Component Metrics**: Add metrics collection and reporting
4. **Component Discovery**: Add service discovery features
5. **Component Dependencies**: Track dependencies between components
6. **Component Versioning**: Track component versions and compatibility

## Conclusion

The runtime API refactoring is complete and functional. The code is now better organized, more maintainable, and follows established patterns. All existing functionality is preserved with backward compatibility, and the new structure makes it easier to extend and maintain the runtime component management system.
