# Credential and Token Caching System

## Overview

NoETL now implements a two-tier credential and token caching system to optimize secret retrieval and token generation during playbook execution.

## Architecture

### Cache Storage

**Backend**: PostgreSQL (`noetl.credential_cache` table)  
**Future**: Support for NATS KV and ValKey distributed stores

### Cache Scopes

#### 1. Execution-Scoped Cache
- **Purpose**: Cache credentials for the duration of a playbook execution
- **Lifetime**: Tied to `execution_id` and `parent_execution_id`
- **Cleanup**: Automatic when parent playbook completes
- **Use Cases**:
  - API keys fetched from external secret managers (Google Secret Manager, AWS Secrets Manager)
  - Database passwords retrieved during workflow
  - One-time credentials that should not persist
- **Cache Key Format**: `{credential_name}:{execution_id}`

#### 2. Global-Scoped Cache
- **Purpose**: Cache authentication tokens across all executions
- **Lifetime**: Based on token expiration (from OAuth `expires_in`, JWT `exp`, etc.)
- **Cleanup**: Automatic expiration via TTL
- **Use Cases**:
  - OAuth access tokens (Google, Amadeus, etc.)
  - Service account tokens
  - JWT bearer tokens
- **Cache Key Format**: `{credential_name}:global:{token_type}`

## Database Schema

```sql
CREATE TABLE noetl.credential_cache (
    cache_key TEXT PRIMARY KEY,
    credential_name TEXT NOT NULL,
    credential_type TEXT NOT NULL,
    cache_type TEXT NOT NULL CHECK (cache_type IN ('secret', 'token')),
    scope_type TEXT NOT NULL CHECK (scope_type IN ('execution', 'global')),
    execution_id BIGINT,
    parent_execution_id BIGINT,
    data_encrypted TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    accessed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    access_count INTEGER DEFAULT 0
);
```

### Key Fields

- **cache_type**: `secret` (raw credentials) or `token` (derived auth tokens)
- **scope_type**: `execution` (playbook-scoped) or `global` (shared)
- **execution_id**: Current execution for execution-scoped entries
- **parent_execution_id**: Top-level execution for hierarchical cleanup
- **data_encrypted**: Encrypted credential/token data using NoETL's encryption system
- **expires_at**: TTL timestamp

## API

### Worker Module: `noetl.worker.credential_cache`

#### Fetch Credential with Auto-Caching

```python
from noetl.worker.credential_cache import fetch_credential_with_cache

credential_data = await fetch_credential_with_cache(
    credential_name='openai_api_key',
    execution_id=507431238966182398,
    parent_execution_id=507431238966182300,
    cache_ttl=3600  # Optional: override default TTL
)
```

**Workflow**:
1. Check cache for `openai_api_key:{execution_id}`
2. If miss, fetch from server (`/api/credentials/openai_api_key?include_data=true`)
3. Store in cache with execution scope
4. Return credential data

#### Store Token in Global Cache

```python
from noetl.worker.credential_cache import store_token_in_cache

await store_token_in_cache(
    credential_name='amadeus_oauth',
    token_data={
        'access_token': 'eyJhbGci...',
        'token_type': 'Bearer',
        'expires_in': 1799
    },
    token_type='oauth',
    expires_in_seconds=1799
)
```

#### Retrieve Token from Global Cache

```python
from noetl.worker.credential_cache import get_token_from_cache

token = await get_token_from_cache(
    credential_name='amadeus_oauth',
    token_type='oauth'
)

if token:
    access_token = token['access_token']
```

#### Cleanup on Execution Complete

```python
from noetl.worker.credential_cache import CredentialCache

await CredentialCache.cleanup_execution(
    execution_id=507431238966182398,
    parent_execution_id=507431238966182300
)
```

## Playbook Integration

### Migration from `tool: secrets`

**Before** (deprecated):
```yaml
- step: get_openai_api_key
  tool: secrets
  provider: google
  project_id: '{{ spec.project_id }}'
  secret_name: openai-api-key
  next:
  - step: use_api_key

- step: use_api_key
  tool: http
  endpoint: https://api.openai.com/v1/chat/completions
  headers:
    Authorization: Bearer {{ get_openai_api_key.secret_value }}
```

**After** (current):
```yaml
workload:
  openai_auth: openai_api_key  # Reference credential by name

workflow:
- step: use_api_key
  tool: http
  endpoint: https://api.openai.com/v1/chat/completions
  auth: '{{ workload.openai_auth }}'  # Auth system handles credential fetch + caching
```

### Token Generation with Caching

```yaml
- step: get_oauth_token
  desc: Get OAuth token with automatic global caching
  tool: python
  args:
    auth_credential: '{{ workload.service_auth }}'
  code: |
    def main(auth_credential):
        import httpx
        
        # Fetch token from OAuth provider
        response = httpx.post(
            "https://oauth.provider.com/token",
            data={
                "grant_type": "client_credentials",
                "client_id": auth_credential['client_id'],
                "client_secret": auth_credential['client_secret']
            }
        )
        token_data = response.json()
        
        # Return token - executor will cache globally
        return {
            "access_token": token_data["access_token"],
            "expires_in": token_data["expires_in"]
        }
```

## Benefits

### Performance
- **Reduced API Calls**: Credentials fetched once per execution, tokens shared globally
- **Faster Execution**: Sub-playbooks reuse parent's cached credentials
- **Lower Latency**: No repeated calls to external secret managers

### Security
- **Encrypted Storage**: All cached data encrypted at rest
- **Automatic Cleanup**: Execution-scoped entries deleted when playbook completes
- **TTL Management**: Expired tokens automatically purged

### Scalability
- **Distributed Ready**: PostgreSQL backend supports multi-worker deployments
- **Future Backends**: NATS KV and ValKey support planned for higher throughput

## Configuration

### Default TTLs

- **Execution-scoped**: 1 hour (or until execution completes)
- **Global tokens**: 24 hours (or token's `expires_in` value)

### Custom TTL

```python
# Override default TTL
await fetch_credential_with_cache(
    credential_name='temp_api_key',
    execution_id=exec_id,
    cache_ttl=300  # 5 minutes
)
```

## Monitoring

### Cache Metrics

Query cache statistics:
```sql
-- Cache hit rate by credential
SELECT 
    credential_name,
    cache_type,
    scope_type,
    COUNT(*) as entries,
    SUM(access_count) as total_accesses,
    AVG(access_count) as avg_accesses
FROM noetl.credential_cache
GROUP BY credential_name, cache_type, scope_type
ORDER BY total_accesses DESC;

-- Expired entries awaiting cleanup
SELECT COUNT(*) as expired_entries
FROM noetl.credential_cache
WHERE expires_at < now();

-- Active execution-scoped entries
SELECT 
    execution_id,
    parent_execution_id,
    COUNT(*) as cached_credentials
FROM noetl.credential_cache
WHERE scope_type = 'execution'
GROUP BY execution_id, parent_execution_id;
```

## Migration Guide

### Step 1: Update Playbooks

Replace all `tool: secrets` steps with `auth` attributes:

```bash
# Find all playbooks using tool: secrets
grep -r "tool: secrets" tests/fixtures/playbooks/
```

### Step 2: Register Credentials

Ensure credentials are registered in NoETL credential store:

```bash
# Register credential
curl -X POST http://localhost:8082/api/credentials \
  -H "Content-Type: application/json" \
  -d '{
    "name": "openai_api_key",
    "type": "httpBearerAuth",
    "data": {
      "api_key": "sk-..."
    }
  }'
```

### Step 3: Update Workload Section

Add credential references:

```yaml
workload:
  openai_auth: openai_api_key
  amadeus_api_auth: amadeus_credentials
```

### Step 4: Test Execution

Verify caching behavior:

```bash
# Execute playbook
noetl execute tests/fixtures/playbooks/api_integration/amadeus_ai_api/amadeus_ai_api.yaml

# Check cache entries
psql -d noetl -c "SELECT * FROM noetl.credential_cache;"
```

## Future Enhancements

### NATS KV Backend
- Distributed cache across workers
- Pub/sub for cache invalidation
- Lower latency for high-throughput workflows

### ValKey Backend
- Redis-compatible in-memory cache
- Cluster mode for HA
- LRU eviction policies

### Cache Warming
- Pre-fetch credentials for scheduled executions
- Batch credential loading
- Predictive token refresh

### Analytics
- Cache hit/miss metrics in ClickHouse
- Credential usage patterns
- Token expiration forecasting

## Related Documentation

- [Token-Based Authentication](./token_auth_implementation.md)
- [Credential Management API](./api_usage.md#credentials)
- [Worker Configuration](./configuration.md#worker-settings)
