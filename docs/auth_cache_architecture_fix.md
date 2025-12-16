# Architecture Compliance Fix: Auth Cache Service Layer

## Problem

The original implementation violated NoETL's core architectural principle:

**VIOLATION**: Workers directly accessing the `noetl` schema database
- File: `noetl/worker/credential_cache.py`
- Issue: Used `get_async_db_connection()` to directly query/modify `noetl.auth_cache` table
- Impact: Broke worker/server separation principle

## Core Architectural Principle

**Workers**: Pure background execution, NO direct access to `noetl` schema
- Communicate only via events or server APIs
- Can query user data tables (postgres plugin)
- CANNOT access `noetl.*` tables directly

**Server**: ONLY component with `noetl` schema database access
- Orchestration and control-flow engine
- Manages catalog, events, queue, variables, auth_cache
- Provides REST APIs for workers to interact with system state

## Solution

### 1. Server-Side Service Layer (NEW)

**File**: `noetl/server/api/auth_cache/service.py`

Created dedicated service layer for server-side database operations:

```python
class AuthCacheService:
    """Server-side authentication cache service."""
    
    @staticmethod
    async def get_cached_token(cache_key: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached token from database with access tracking."""
        async with get_async_db_connection() as conn:
            # Direct SQL to noetl.auth_cache (server-side only)
            ...
    
    @staticmethod
    async def set_cached_token(cache_key, token_data, ...) -> bool:
        """Store token in cache database with encryption."""
        async with get_async_db_connection() as conn:
            # Direct SQL to noetl.auth_cache (server-side only)
            ...
    
    @staticmethod
    async def delete_cached_token(cache_key: str) -> bool:
        """Delete cached token from database."""
        ...
    
    @staticmethod
    async def cleanup_execution(execution_id: int) -> int:
        """Clean up execution-scoped cache entries."""
        ...
    
    @staticmethod
    async def cleanup_expired() -> int:
        """Clean up expired cache entries."""
        ...
```

**Key Points**:
- Uses `get_async_db_connection()` for direct database access
- Handles encryption/decryption with `encrypt_json()`/`decrypt_json()`
- Manages all CRUD operations on `noetl.auth_cache` table
- Only imported and used by server-side code

### 2. Worker-Side API Client (REFACTORED)

**File**: `noetl/worker/credential_cache.py`

Converted from database accessor to HTTP API client:

```python
class CredentialCache:
    """Credential and token caching API client for workers."""
    
    @staticmethod
    async def get_cached(credential_name, execution_id=None, token_type=None):
        """Retrieve cached token via server API."""
        api_url = f"{server_url}/api/auth-cache/{cache_key}"
        async with httpx.AsyncClient() as client:
            response = await client.get(api_url)
            # Process response, return decrypted data
    
    @staticmethod
    async def set_cached(credential_name, data, ...):
        """Store token via server API."""
        api_url = f"{server_url}/api/auth-cache/{cache_key}"
        async with httpx.AsyncClient() as client:
            response = await client.post(api_url, json=payload)
            # Return success/failure
    
    @staticmethod
    async def delete_cached(credential_name, ...):
        """Delete token via server API."""
        api_url = f"{server_url}/api/auth-cache/{cache_key}"
        async with httpx.AsyncClient() as client:
            response = await client.delete(api_url)
            # Return success/failure
```

**Key Points**:
- Uses `httpx.AsyncClient` for HTTP API calls
- NO database imports (`get_async_db_connection` removed)
- Communicates only with server via REST API
- Maintains same interface for backward compatibility

### 3. API Endpoint Updates

**File**: `noetl/server/api/auth_cache/endpoint.py`

Updated all endpoints to use service layer instead of worker's CredentialCache:

**Before** (WRONG):
```python
from noetl.worker.credential_cache import CredentialCache

@router.get("/{cache_key}")
async def get_cached_token(cache_key: str):
    cached = await CredentialCache.get_cached(...)  # ❌ Worker accessing DB
    return TokenCacheGetResponse(...)
```

**After** (CORRECT):
```python
from .service import AuthCacheService

@router.get("/{cache_key}")
async def get_cached_token(cache_key: str):
    cached = await AuthCacheService.get_cached_token(cache_key)  # ✅ Server service
    return TokenCacheGetResponse(...)
```

**Changes**:
- Import: `from .service import AuthCacheService` instead of worker's CredentialCache
- GET endpoint: Use `AuthCacheService.get_cached_token(cache_key)`
- POST endpoint: Use `AuthCacheService.set_cached_token(cache_key, ...)`
- DELETE endpoint: Use `AuthCacheService.delete_cached_token(cache_key)`

### 4. Playbook Integration (UNCHANGED)

**File**: `tests/fixtures/playbooks/.../amadeus_ai_api.yaml`

Playbook already uses correct pattern - HTTP sink calling server API:

```yaml
- step: get_amadeus_token
  tool: http
  endpoint: https://test.api.amadeus.com/v1/security/oauth2/token
  case:
    - when: "{{ event.name == 'call.done' and response.data.access_token }}"
      then:
        sink:
          tool: http  # ✅ Worker calls server API
          method: POST
          endpoint: "http://noetl.noetl.svc.cluster.local:8080/api/auth-cache/..."
          payload:
            token_data: { access_token, token_type, expires_in }
            credential_type: oauth2_client_credentials
            scope_type: global
            ttl_seconds: "{{ (response.data.expires_in | int - 300) }}"
```

**Flow**:
1. Worker executes HTTP action to fetch token from Amadeus
2. Worker sends HTTP POST to server's auth_cache API (sink block)
3. Server's API endpoint receives request
4. Server's service layer encrypts and stores in `noetl.auth_cache` table
5. Response returned to worker

## Architecture Compliance Verification

### ✅ Correct Pattern (Now Implemented)

**Workers**:
- Call HTTP APIs: `POST /api/auth-cache/{cache_key}` ✅
- Use `httpx.AsyncClient` for communication ✅
- NO `noetl.*` table access ✅

**Server**:
- Provides REST API endpoints ✅
- Service layer handles database operations ✅
- Direct access to `noetl.auth_cache` table ✅

### ❌ Violation Pattern (Fixed)

**Before**:
```python
# noetl/worker/credential_cache.py (OLD - REMOVED)
from noetl.core.common import get_async_db_connection  # ❌

async def get_cached(...):
    async with get_async_db_connection() as conn:  # ❌ Worker accessing DB
        await cursor.execute("SELECT FROM noetl.auth_cache ...")  # ❌
```

**After**:
```python
# noetl/worker/credential_cache.py (NEW - API CLIENT)
import httpx  # ✅

async def get_cached(...):
    async with httpx.AsyncClient() as client:  # ✅ Worker calling API
        response = await client.get(api_url)  # ✅
```

## Files Changed

### Created
1. `noetl/server/api/auth_cache/service.py` - Server-side database service
2. `noetl/worker/credential_cache_old.py` - Backup of old implementation

### Modified
1. `noetl/worker/credential_cache.py` - Converted to API client
2. `noetl/server/api/auth_cache/endpoint.py` - Updated to use service layer

### Unchanged (Working Correctly)
1. `noetl/server/api/auth_cache/schema.py` - Pydantic models
2. `noetl/server/api/auth_cache/__init__.py` - Router export
3. `tests/fixtures/playbooks/.../amadeus_ai_api.yaml` - HTTP sink pattern
4. `noetl/plugin/shared/auth/utils.py` - Uses worker's CredentialCache (API client)

## Testing Plan

### 1. API Direct Testing
```bash
# Test GET (should return 404 initially)
curl http://localhost:8082/api/auth-cache/test_token:global:oauth2

# Test POST (cache a token)
curl -X POST http://localhost:8082/api/auth-cache/test_token:global:oauth2 \
  -H "Content-Type: application/json" \
  -d '{
    "token_data": {"access_token": "test123", "token_type": "bearer"},
    "credential_type": "oauth2_client_credentials",
    "scope_type": "global",
    "ttl_seconds": 3600
  }'

# Test GET (should return cached token)
curl http://localhost:8082/api/auth-cache/test_token:global:oauth2

# Test DELETE
curl -X DELETE http://localhost:8082/api/auth-cache/test_token:global:oauth2
```

### 2. End-to-End Playbook Testing
```bash
# Register Amadeus playbook
task register-playbook-amadeus

# Execute first time (fetch token, cache it)
curl -X POST http://localhost:8082/api/catalog/execute \
  -H "Content-Type: application/json" \
  -d '{
    "catalog_path": "/amadeus/ai_api",
    "payload": {...}
  }'

# Execute second time (use cached token)
curl -X POST http://localhost:8082/api/catalog/execute \
  -H "Content-Type: application/json" \
  -d '{
    "catalog_path": "/amadeus/ai_api",
    "payload": {...}
  }'

# Verify: Check that second execution skips Amadeus OAuth call
```

### 3. Database Verification
```bash
# Query auth_cache table via server API
curl -X POST http://localhost:8082/api/postgres/execute \
  -H "Content-Type: application/json" \
  -d '{
    "query": "SELECT cache_key, credential_type, scope_type, expires_at, access_count FROM noetl.auth_cache",
    "schema": "noetl"
  }'
```

## Benefits of Architecture Compliance

1. **Clear Separation of Concerns**
   - Workers: Execution only
   - Server: State management and coordination

2. **Security**
   - Workers cannot bypass server's access control
   - All auth_cache operations audited through API endpoints

3. **Scalability**
   - Workers are stateless API clients
   - Server can scale database connections independently

4. **Maintainability**
   - Single source of truth for database operations (service layer)
   - API contract clearly defined with Pydantic schemas

5. **Testing**
   - Can test service layer independently
   - Can mock HTTP APIs for worker testing

## Deployment

**Docker Image**: `local/noetl:2025-12-15-22-57`

**Status**: 
- Built: ✅
- Loaded to kind cluster: ✅
- Deployed: ✅
- Pods running: ✅

**Next Steps**:
1. Test auth_cache API endpoints
2. Test Amadeus playbook with token caching
3. Verify token reuse across executions
4. Commit changes to git

## Summary

This refactoring fixes a critical architecture violation where workers were directly accessing the `noetl` schema database. The solution implements proper separation:

- **Server service layer** handles all database operations
- **Worker API client** communicates only via HTTP
- **API endpoints** delegate to service layer
- **Playbooks** use HTTP sink pattern to call APIs

The system now complies with NoETL's core principle: **workers never access noetl schema directly**.
