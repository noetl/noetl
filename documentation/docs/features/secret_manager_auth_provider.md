# Secret Manager Authentication Provider

This document describes the Secret Manager authentication provider implementation in NoETL, which enables secure credential retrieval from external secret management systems like Google Secret Manager.

## Overview

The Secret Manager provider extends NoETL's unified authentication system to support fetching credentials from external secret stores at runtime, rather than storing them in the NoETL credential database.

### Key Features

- **OAuth-Based Access**: Uses OAuth tokens to authenticate with Secret Manager APIs
- **Automatic Caching**: Credentials cached for 1 hour (execution-scoped) to reduce API calls
- **Multi-Value Support**: Handles both single-value secrets (API keys) and multi-value secrets (OAuth client credentials)
- **Template Integration**: Fetched credentials available in Jinja2 templates
- **Provider Abstraction**: Extensible to support multiple secret management systems

## Architecture

### Components

1. **Auth Resolver** (`noetl/tools/shared/auth/resolver.py`):
   - Detects `provider: secret_manager` in auth configuration
   - Delegates to secret fetching utilities
   - Injects resolved credentials into template context

2. **Secret Manager Utils** (`noetl/tools/shared/auth/utils.py`):
   - `fetch_secret_manager_value()`: Main entry point for secret retrieval
   - `_fetch_google_secret()`: Google Secret Manager API integration
   - Handles OAuth token resolution and API calls

3. **Credential Cache** (`noetl/database/credential_cache.py`):
   - Stores fetched secrets in `noetl.credential_cache` table
   - TTL-based expiration (default: 3600 seconds)
   - Execution-scoped isolation

### Flow Diagram

```
Playbook Auth Config
        ↓
Auth Resolver (resolve_auth_map)
        ↓
Detect provider=secret_manager
        ↓
fetch_secret_manager_value()
        ↓
Check Cache (CredentialCache.get_cached)
        ↓
    [Hit] → Return cached value
    [Miss] → ↓
        ↓
Resolve OAuth Token (resolve_token)
        ↓
Call Secret Manager API
        ↓
Decode Base64 Secret
        ↓
Cache with TTL (CredentialCache.set_cached)
        ↓
Return Secret Value
        ↓
Inject into Template Context
        ↓
Available as {{ auth.alias.field }}
```

## Configuration Syntax

### Single-Value Secrets (API Keys, Tokens)

For secrets with a single value (API keys, bearer tokens):

```yaml
auth:
  openai:
    type: bearer              # Auth type
    provider: secret_manager  # Use Secret Manager provider
    key: projects/123/secrets/openai-api-key/versions/1  # Secret path
    oauth_credential: google_oauth  # OAuth credential for Secret Manager access
```

**Template Usage**:
```yaml
headers:
  Authorization: Bearer {{ auth.openai.token }}
```

### Multi-Value Secrets (OAuth Client Credentials)

For secrets requiring multiple values (OAuth client ID + secret):

```yaml
auth:
  amadeus:
    type: oauth2_client_credentials
    provider: secret_manager
    client_id_key: projects/123/secrets/amadeus-client-id/versions/1
    client_secret_key: projects/123/secrets/amadeus-client-secret/versions/1
    oauth_credential: google_oauth
```

**Template Usage**:
```yaml
data:
  grant_type: client_credentials
  client_id: '{{ auth.amadeus.client_id }}'
  client_secret: '{{ auth.amadeus.client_secret }}'
```

### Supported Auth Types

The Secret Manager provider works with all NoETL auth types:

- `bearer` - Bearer token authentication (single `key`)
- `api_key` - API key authentication (single `key`)
- `basic` - Basic authentication (single `key` containing `username:password`)
- `header` - Custom header authentication (single `key`)
- `oauth2_client_credentials` - OAuth client credentials (`client_id_key` + `client_secret_key`)

## Implementation Details

### Google Secret Manager Integration

**API Endpoint**:
```
GET https://secretmanager.googleapis.com/v1/{secret_path}:access
Authorization: Bearer {oauth_token}
```

**Response Format**:
```json
{
  "name": "projects/123/secrets/api-key/versions/1",
  "payload": {
    "data": "BASE64_ENCODED_SECRET_VALUE"
  }
}
```

**Code Implementation** (`noetl/tools/shared/auth/utils.py`):

```python
def fetch_secret_manager_value(key, auth_type, oauth_credential, execution_id):
    """
    Fetch a secret from Secret Manager with caching.
    
    Args:
        key: Secret path (e.g., "projects/123/secrets/api-key/versions/1")
        auth_type: Authentication type (bearer, api_key, etc.)
        oauth_credential: OAuth credential reference for Secret Manager API
        execution_id: Execution ID for cache scoping
        
    Returns:
        Secret value (plain text)
    """
    # 1. Check cache
    credential_name = f"secret_manager_{key.replace('/', '_')}"
    cached = CredentialCache.get_cached(credential_name, execution_id, 'execution')
    if cached:
        return cached
    
    # 2. Detect provider (GCP, AWS, etc.)
    if key.startswith("projects/"):
        secret_value = _fetch_google_secret(key, oauth_credential)
    else:
        # Fallback to environment variable
        secret_value = os.getenv(key)
    
    # 3. Cache for 1 hour
    if secret_value:
        CredentialCache.set_cached(
            credential_name, execution_id, 'execution', secret_value, 3600
        )
    
    return secret_value


def _fetch_google_secret(secret_path, oauth_credential):
    """
    Fetch secret from Google Secret Manager API.
    
    Args:
        secret_path: Full secret path with version
        oauth_credential: OAuth credential for authentication
        
    Returns:
        Decoded secret value
    """
    # Resolve OAuth token
    token_response = resolve_token(oauth_credential)
    access_token = token_response['access_token']
    
    # Call Secret Manager API
    url = f"https://secretmanager.googleapis.com/v1/{secret_path}:access"
    response = httpx.Client().get(
        url,
        headers={'Authorization': f'Bearer {access_token}'}
    )
    response.raise_for_status()
    
    # Decode base64 payload
    payload_data = response.json()['payload']['data']
    return base64.b64decode(payload_data).decode('UTF-8')
```

### Auth Resolution Logic

**Code Implementation** (`noetl/tools/shared/auth/resolver.py`):

```python
def resolve_auth_map(step_config, task_with, jinja_env, context):
    """Resolve authentication configuration."""
    auth_config = step_config.get('auth') or task_with.get('auth')
    if not auth_config:
        return ({}, {})
    
    resolved_map = {}
    
    for alias, spec in auth_config.items():
        auth_type = spec.get('type')
        provider = spec.get('provider', 'credential_store')
        
        # Secret Manager provider handling
        if provider == 'secret_manager':
            oauth_cred = spec.get('oauth_credential')
            execution_id = context.get('execution_id')
            
            # Multi-value secrets (oauth2_client_credentials)
            if auth_type == 'oauth2_client_credentials':
                client_id_key = spec.get('client_id_key')
                client_secret_key = spec.get('client_secret_key')
                
                client_id = fetch_secret_manager_value(
                    client_id_key, 'api_key', oauth_cred, execution_id
                )
                client_secret = fetch_secret_manager_value(
                    client_secret_key, 'api_key', oauth_cred, execution_id
                )
                
                resolved_map[alias] = {
                    'client_id': client_id,
                    'client_secret': client_secret
                }
            
            # Single-value secrets
            elif 'key' in spec:
                key = spec['key']
                secret_value = fetch_secret_manager_value(
                    key, auth_type, oauth_cred, execution_id
                )
                
                # Map to appropriate field based on auth type
                if auth_type == 'bearer':
                    resolved_map[alias] = {'token': secret_value}
                elif auth_type == 'api_key':
                    resolved_map[alias] = {'api_key': secret_value}
                # ... other mappings
    
    return ({}, resolved_map)
```

### HTTP Tool Integration

The HTTP executor injects resolved auth into template context:

```python
# noetl/tools/tools/http/executor.py

# Resolve auth BEFORE rendering data/payload
auth_headers, resolved_auth_map = _process_authentication_with_context(...)

if resolved_auth_map:
    context['auth'] = resolved_auth_map  # Inject for templates

# NOW render data/payload with auth in context
data_map = render_template(jinja_env, raw_data or {}, context)
payload = render_template(jinja_env, raw_payload or {}, context)
```

## Credential Caching

### Database Schema

```sql
CREATE TABLE IF NOT EXISTS noetl.credential_cache (
    credential_name VARCHAR(255),
    execution_id BIGINT,
    scope VARCHAR(50),
    credential_data TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    access_count INTEGER DEFAULT 1,
    PRIMARY KEY (credential_name, execution_id, scope)
);

CREATE INDEX idx_credential_cache_expires ON noetl.credential_cache(expires_at);
```

### Cache Operations

**Set Cache**:
```python
CredentialCache.set_cached(
    credential_name='secret_manager_projects_123_secrets_api_key_versions_1',
    execution_id=507598625225048802,
    scope='execution',
    credential_data='sk-abc123...',
    ttl_seconds=3600
)
```

**Get Cache**:
```python
cached_value = CredentialCache.get_cached(
    credential_name='secret_manager_projects_123_secrets_api_key_versions_1',
    execution_id=507598625225048802,
    scope='execution'
)
```

**Cache Cleanup**:
```sql
DELETE FROM noetl.credential_cache 
WHERE expires_at < CURRENT_TIMESTAMP;
```

### Performance Impact

**Without Caching**:
- 3 Secret Manager API calls per execution
- ~150ms latency per call
- Total overhead: ~450ms

**With Caching** (after first execution):
- 0 Secret Manager API calls
- Cache lookup: ~5ms
- Total overhead: ~15ms
- **Speedup**: 30x faster

## Security Considerations

### Credential Isolation

- **Execution Scope**: Credentials cached per execution ID
- **No Cross-Execution Access**: Each execution has isolated cache
- **Automatic Cleanup**: Expired credentials purged on cache miss

### OAuth Token Security

- **Short-Lived**: OAuth tokens typically valid for 1 hour
- **Automatic Refresh**: Token resolution handles expiration
- **Minimal Permissions**: Service accounts with Secret Manager read-only access

### Secret Manager Permissions

Required Google Cloud IAM permissions:
```
roles/secretmanager.secretAccessor
```

On specific secrets:
```bash
gcloud secrets add-iam-policy-binding SECRET_NAME \
  --member="serviceAccount:SERVICE_ACCOUNT_EMAIL" \
  --role="roles/secretmanager.secretAccessor"
```

### Audit Logging

All Secret Manager access logged in:
1. **Google Cloud Audit Logs**: API calls, timestamps, caller identity
2. **NoETL Execution Events**: Credential resolution in step context
3. **Credential Cache Table**: Access count, timestamps

## Extensibility

### Adding New Providers

To support additional secret management systems (AWS Secrets Manager, Azure Key Vault):

1. **Add Provider Detection** (`utils.py`):
```python
def fetch_secret_manager_value(key, auth_type, oauth_credential, execution_id):
    if key.startswith("projects/"):  # GCP
        return _fetch_google_secret(key, oauth_credential)
    elif key.startswith("arn:aws:"):  # AWS
        return _fetch_aws_secret(key, oauth_credential)
    elif key.startswith("https://"):  # Azure
        return _fetch_azure_secret(key, oauth_credential)
```

2. **Implement Provider Function**:
```python
def _fetch_aws_secret(secret_arn, oauth_credential):
    # AWS Secrets Manager API integration
    session = boto3.Session()
    client = session.client('secretsmanager')
    response = client.get_secret_value(SecretId=secret_arn)
    return response['SecretString']
```

3. **Update Constants** (`constants.py`):
```python
SECRET_MANAGER_PROVIDERS = ['gcp', 'aws', 'azure']
```

## Testing

### Unit Tests

```python
def test_secret_manager_bearer_auth():
    """Test bearer token from Secret Manager."""
    auth_config = {
        'openai': {
            'type': 'bearer',
            'provider': 'secret_manager',
            'key': 'projects/123/secrets/openai-api-key/versions/1',
            'oauth_credential': 'google_oauth'
        }
    }
    
    headers, auth_map = resolve_auth_map(
        {'auth': auth_config}, {}, jinja_env, context
    )
    
    assert 'openai' in auth_map
    assert 'token' in auth_map['openai']
    assert auth_map['openai']['token'].startswith('sk-')


def test_secret_manager_oauth_credentials():
    """Test OAuth client credentials from Secret Manager."""
    auth_config = {
        'amadeus': {
            'type': 'oauth2_client_credentials',
            'provider': 'secret_manager',
            'client_id_key': 'projects/123/secrets/client-id/versions/1',
            'client_secret_key': 'projects/123/secrets/client-secret/versions/1',
            'oauth_credential': 'google_oauth'
        }
    }
    
    headers, auth_map = resolve_auth_map(
        {'auth': auth_config}, {}, jinja_env, context
    )
    
    assert 'amadeus' in auth_map
    assert 'client_id' in auth_map['amadeus']
    assert 'client_secret' in auth_map['amadeus']
```

### Integration Tests

See `tests/fixtures/playbooks/api_integration/amadeus_ai_api/` for complete example.

## Migration Guide

### From Manual Secret Fetching

**Before** (17 steps with manual secret handling):
```yaml
- step: get_openai_api_key
  tool: http
  method: GET
  endpoint: https://secretmanager.googleapis.com/v1/...
  # ... manual HTTP call

- step: parse_openai_key
  tool: python
  code: |
    import base64
    def main(response):
        return base64.b64decode(response['payload']['data']).decode()

- step: call_openai
  tool: http
  headers:
    Authorization: Bearer {{ parse_openai_key }}
```

**After** (11 steps with declarative auth):
```yaml
- step: call_openai
  tool: http
  auth:
    openai:
      type: bearer
      provider: secret_manager
      key: projects/123/secrets/openai-api-key/versions/1
      oauth_credential: google_oauth
  # Auth automatically injected
```

**Benefits**:
- 6 fewer steps
- Automatic caching
- Template integration
- Better security (no secrets in step results)

## Troubleshooting

### "Failed to retrieve secret" Error

**Causes**:
1. Invalid secret path
2. Missing Secret Manager permissions
3. Expired OAuth token
4. Secret not found

**Resolution**:
```bash
# Verify secret exists
gcloud secrets versions access latest --secret=SECRET_NAME

# Check permissions
gcloud secrets get-iam-policy SECRET_NAME

# Test OAuth credential
curl -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  https://secretmanager.googleapis.com/v1/projects/PROJECT/secrets/SECRET/versions/latest:access
```

### "Auth missing 'key'" Error

**Cause**: Wrong provider or missing key field

**Resolution**:
```yaml
# ❌ Wrong
auth:
  api:
    type: bearer
    provider: secret_manager
    # Missing 'key' field

# ✅ Correct
auth:
  api:
    type: bearer
    provider: secret_manager
    key: projects/123/secrets/api-key/versions/1
    oauth_credential: google_oauth
```

### Cache Not Working

**Symptoms**: Multiple Secret Manager calls per execution

**Causes**:
1. Different execution IDs
2. Cache table doesn't exist
3. TTL expired

**Resolution**:
```sql
-- Check cache table
SELECT * FROM noetl.credential_cache 
WHERE execution_id = YOUR_EXECUTION_ID;

-- Check expiration
SELECT credential_name, 
       expires_at > CURRENT_TIMESTAMP as is_valid,
       access_count 
FROM noetl.credential_cache;
```

## Best Practices

1. **Use Version-Pinned Secrets**: Specify version (e.g., `/versions/1`) for reproducibility
2. **Minimize Secret Access**: Use caching effectively
3. **Scope Credentials**: Use execution-scoped caching for isolation
4. **Rotate Secrets**: Update Secret Manager versions, not playbooks
5. **Monitor Access**: Review Cloud Audit Logs regularly
6. **Least Privilege**: Grant minimal required permissions
7. **Separate OAuth Credentials**: One OAuth credential per environment
8. **Template Validation**: Test auth templates before production

## References

- [Auth Reference](/docs/reference/auth_and_keychain_reference)
- [Google Secret Manager API](https://cloud.google.com/secret-manager/docs/reference/rest)
- [Credential Caching](/docs/features/credential_caching)
- [API Integration Examples](https://github.com/noetl/noetl/tree/main/tests/fixtures/playbooks/api_integration)
