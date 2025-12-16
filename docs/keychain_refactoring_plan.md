# Keychain Refactoring Plan

## Overview
Refactor credential handling from `auth_cache` to `keychain` with catalog_id scoping and auto-renewal capabilities.

## Database Changes ✅

### Schema (`noetl/database/ddl/postgres/schema_ddl.sql`)
- Table renamed: `auth_cache` → `keychain`
- Added columns:
  - `keychain_name TEXT NOT NULL` (replaces credential_name)
  - `catalog_id BIGINT NOT NULL REFERENCES noetl.catalog(catalog_id)`
  - `auto_renew BOOLEAN DEFAULT false`
  - `renew_config JSONB`
- Updated scope_type: `('execution', 'global')` → `('local', 'global', 'shared')`
- New indexes:
  - `idx_keychain_name` on `keychain_name`
  - `idx_keychain_catalog` on `catalog_id`
  - `idx_keychain_name_catalog` on `(keychain_name, catalog_id)`

### Cache Key Format
- **Old**: `{credential_name}:{execution_id}` or `{credential_name}:global:{token_type}`
- **New**: 
  - Local: `{keychain_name}:{catalog_id}:{execution_id}`
  - Shared: `{keychain_name}:{catalog_id}:shared:{execution_id}`
  - Global: `{keychain_name}:{catalog_id}:global`

## API Changes

### Directory Structure
```
noetl/server/api/
  keychain/              # Renamed from auth_cache
    __init__.py
    service.py          # NEW: KeychainService class
    endpoint.py         # Updated endpoints
    schema.py           # Update request/response models
```

### Endpoint Changes
- **Path**: `/api/auth-cache` → `/api/keychain`
- **Service**: `AuthCacheService` → `KeychainService`

### New Endpoints
```
GET    /api/keychain/{catalog_id}/{keychain_name}
POST   /api/keychain/{catalog_id}/{keychain_name}
DELETE /api/keychain/{catalog_id}/{keychain_name}
GET    /api/keychain/catalog/{catalog_id}  # List all entries for catalog
```

### Request/Response Models (`schema.py`)
Update to include:
- `keychain_name` (required)
- `catalog_id` (required)
- `auto_renew` (optional, default false)
- `renew_config` (optional, for auto-renewal)

## Playbook DSL Changes

### New `keychain` Block
```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: amadeus_ai_api
  path: api_integration/amadeus_ai_api

keychain:
  - name: amadeus_credentials
    kind: secret_manager
    provider: gcp
    auth: google_oauth
    scope: global  # local, global, shared
    map:
      client_id_key: '{{ workload.amadeus_key_path }}'
      client_secret_key: '{{ workload.amadeus_secret_path }}'
      oauth_credential: '{{ workload.oauth_cred }}'

  - name: amadeus_token
    kind: oauth2
    scope: global
    auto_renew: true
    endpoint: https://test.api.amadeus.com/v1/security/oauth2/token
    headers:
      Content-Type: application/x-www-form-urlencoded
    data:
      grant_type: client_credentials
      client_id: '{{ keychain.amadeus_credentials.client_id }}'
      client_secret: '{{ keychain.amadeus_credentials.client_secret }}'
    ttl: "{{ response.expires_in | int - 300 }}"

workflow:
  - step: start
    next:
      - step: query_amadeus
  
  - step: query_amadeus
    tool:
      kind: http
      method: GET
      endpoint: https://test.api.amadeus.com/v2/shopping/flight-offers
      auth: "{{ keychain.amadeus_token }}"  # Auto-fetches/renews token
      params:
        query: "{{ workload.user_query }}"
    next:
      - step: end
  
  - step: end
    desc: Complete
```

### Auth Reference Syntax
```yaml
# OLD approach - manual token management
auth:
  amadeus:
    type: oauth2_client_credentials
    provider: secret_manager
    client_id_key: '{{ workload.amadeus_key_path }}'

# NEW approach - keychain reference
auth: "{{ keychain.amadeus_token }}"

# Or explicit
auth:
  type: keychain
  name: amadeus_token
```

### Auto-Renewal Flow
1. Worker requests `{{ keychain.amadeus_token }}`
2. Server checks keychain table for `amadeus_token` + `catalog_id`
3. If found and valid → return token
4. If expired and `auto_renew=true` → execute renew_config
5. If not found → execute keychain definition from playbook
6. Cache result in keychain table

## Plugin Integration

### HTTP Plugin (`noetl/plugin/http.py`)
```python
# Before executing HTTP request
if 'auth' in tool_config:
    auth_value = tool_config['auth']
    
    # Check if it's a keychain reference
    if isinstance(auth_value, str) and '{{ keychain.' in auth_value:
        keychain_name = extract_keychain_name(auth_value)
        token_data = await resolve_keychain(
            keychain_name=keychain_name,
            catalog_id=execution_context.catalog_id,
            execution_id=execution_context.execution_id
        )
        headers['Authorization'] = f"Bearer {token_data['access_token']}"
```

### Postgres Plugin (`noetl/plugin/postgres.py`)
```python
if 'auth' in tool_config:
    auth_value = tool_config['auth']
    
    if isinstance(auth_value, str) and '{{ keychain.' in auth_value:
        keychain_name = extract_keychain_name(auth_value)
        creds = await resolve_keychain(
            keychain_name=keychain_name,
            catalog_id=execution_context.catalog_id,
            execution_id=execution_context.execution_id
        )
        connection_string = build_postgres_connection(creds)
```

### Unified Auth Resolution (`noetl/plugin/shared/auth/keychain.py`)
```python
async def resolve_keychain(
    keychain_name: str,
    catalog_id: int,
    execution_id: Optional[int] = None,
    auto_renew: bool = True
) -> Dict[str, Any]:
    """
    Resolve keychain entry, handling expiration and auto-renewal.
    
    Flow:
    1. Query keychain table for entry
    2. If found and valid → return data
    3. If expired and auto_renew → trigger renewal
    4. If not found → fetch from playbook definition
    5. Cache result
    """
    # Call server API /api/keychain/{catalog_id}/{keychain_name}
    result = await keychain_api.get_entry(
        catalog_id=catalog_id,
        keychain_name=keychain_name,
        execution_id=execution_id
    )
    
    if result and not result.get('expired'):
        return result['data']
    
    if result and result.get('expired') and result.get('auto_renew'):
        # Trigger renewal
        renewed = await renew_keychain_entry(
            keychain_name=keychain_name,
            catalog_id=catalog_id,
            renew_config=result['renew_config']
        )
        return renewed['data']
    
    # Fetch from playbook definition
    keychain_def = await get_keychain_definition(catalog_id, keychain_name)
    token_data = await execute_keychain_definition(keychain_def)
    
    # Cache it
    await keychain_api.set_entry(
        catalog_id=catalog_id,
        keychain_name=keychain_name,
        token_data=token_data,
        **keychain_def.get('cache_options', {})
    )
    
    return token_data
```

## File Checklist

### Completed ✅
- [x] `noetl/database/ddl/postgres/schema_ddl.sql` - Schema updated
- [x] `noetl/server/api/keychain/service.py` - New KeychainService
- [x] `noetl/server/api/__init__.py` - Router registration updated

### TODO
- [ ] `noetl/server/api/keychain/endpoint.py` - Update to new API paths and service
- [ ] `noetl/server/api/keychain/schema.py` - Update request/response models
- [ ] `noetl/core/dsl/parser.py` - Parse `keychain` block from playbook
- [ ] `noetl/core/dsl/validator.py` - Validate keychain definitions
- [ ] `noetl/plugin/shared/auth/keychain.py` - NEW: Unified keychain resolver
- [ ] `noetl/plugin/http.py` - Integrate keychain auth
- [ ] `noetl/plugin/postgres.py` - Integrate keychain auth
- [ ] `noetl/plugin/snowflake.py` - Integrate keychain auth
- [ ] `noetl/plugin/duckdb.py` - Integrate keychain auth
- [ ] `noetl/worker/credential_cache.py` - Update to call new /api/keychain endpoints
- [ ] Update playbook: `tests/fixtures/playbooks/api_integration/amadeus_ai_api/amadeus_ai_api.yaml`

## Migration Path

### Step 1: Update Schema
```sql
-- Apply schema changes
-- This breaks backward compatibility (as requested)
```

### Step 2: Update Server Code
- Service layer
- API endpoints
- Router registration

### Step 3: Update Worker Code
- credential_cache.py → calls new keychain API
- Plugin auth resolution

### Step 4: Update DSL Parser
- Parse `keychain` block
- Validate definitions
- Store in catalog metadata

### Step 5: Update Playbooks
- Remove manual token fetching steps
- Define keychain entries
- Use `{{ keychain.name }}` references

## Testing Strategy

1. **Unit Tests**: KeychainService CRUD operations
2. **Integration Tests**: Keychain resolution in plugins
3. **End-to-End Tests**: Amadeus playbook with keychain
4. **Auto-Renewal Test**: Expire token and verify renewal

## Benefits

1. **Declarative**: Auth defined once in keychain block
2. **Auto-Renewal**: No manual token refresh steps
3. **Scoped**: Catalog-level isolation
4. **Reusable**: Reference same keychain in multiple steps
5. **Secure**: Encrypted storage, TTL management
6. **Auditable**: Access tracking per entry
