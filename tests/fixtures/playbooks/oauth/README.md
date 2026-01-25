# OAuth Test Playbooks

This directory contains test playbooks for OAuth-based authentication with various cloud services and APIs.

## Available Tests

### ✅ Implemented

1. **Google Secret Manager** (`google_secret_manager/`)
   - Tests OAuth token generation with Google service accounts
   - Accesses secrets from Google Secret Manager
   - Uses `token()` Jinja2 function for dynamic token injection
   - **Status**: Fully implemented and tested

2. **Google Cloud Storage** (`google_gcs/`)
   - Tests GCS API access with OAuth tokens
   - Lists buckets, retrieves object metadata, downloads objects
   - Uses devstorage.read_only scope
   - **Status**: Fully implemented and tested

### 🚧 Planned

3. **Interactive Brokers** (`interactive_brokers/`)
   - OAuth-based trading API access
   - Account info, positions, market data
   - **Status**: Placeholder - implementation pending

## Quick Start

### 1. Prerequisites

```bash
# Start NoETL locally
noetl run automation/setup/local-start.yaml

# Verify services are running
noetl run automation/setup/local-status.yaml
```

### 2. Set Up Credentials

For Google services, you need a service account JSON key:

```bash
# Download from GCP Console
cd tests/fixtures/credentials

# Copy example template
cp google_oauth.json.example google_oauth.json

# Edit with your service account key
vim google_oauth.json

# Register credential
curl -X POST http://localhost:8083/api/credentials \
  -H 'Content-Type: application/json' \
  --data-binary @google_oauth.json
```

See `tests/fixtures/credentials/README.md` for detailed setup instructions.

### 3. Run Tests

```bash
# Test Secret Manager
noetl run tests/fixtures/playbooks/oauth/google_secret_manager/google_secret_manager.yaml

# Test GCS
noetl run tests/fixtures/playbooks/oauth/google_gcs/google_gcs.yaml
```

## How OAuth Works in NoETL

### Token Generation

NoETL uses the `token()` function in Jinja2 templates:

```yaml
- step: call_api
  tool: http
  url: "https://api.example.com/resource"
  headers:
    Authorization: "Bearer {{ token('credential_name', 'https://api.example.com/') }}"
```

**What happens**:
1. `token()` function is called during template rendering
2. NoETL fetches credential from database
3. Credential data is decrypted
4. Appropriate `TokenProvider` is instantiated (Google, IB, etc.)
5. Token is generated/refreshed if needed
6. Token is cached with expiration
7. Token is injected into the HTTP header

### Token Caching

Tokens are cached with a 50-minute buffer before expiration:

```python
# From noetl/core/auth/providers.py
def fetch_token(self, audience: Optional[str] = None) -> str:
    if not self.is_token_valid():
        self._cached_token = self._fetch_token_impl(audience)
        self._token_expiry = datetime.now(timezone.utc) + timedelta(minutes=50)
    return self._cached_token
```

### Supported Providers

Current token providers:

1. **GoogleTokenProvider** (`noetl/core/auth/google_provider.py`)
   - Service account authentication
   - Service account impersonation
   - ID tokens (with audience)
   - Access tokens

2. **IBTokenProvider** (planned)
   - Client credentials OAuth flow
   - Token refresh

## Architecture

```
┌─────────────────┐
│  Playbook YAML  │
│  {{ token() }}  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Jinja2 Renderer │
│ (Worker)        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Token Resolver  │
│ resolve_token() │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Fetch Credential│
│ (Encrypted DB)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ TokenProvider   │
│ Factory         │
└────────┬────────┘
         │
         ├─────────────┬─────────────┐
         ▼             ▼             ▼
┌──────────────┐ ┌──────────┐ ┌─────────┐
│   Google     │ │    IB    │ │  Future │
│  Provider    │ │ Provider │ │ Providers│
└──────────────┘ └──────────┘ └─────────┘
         │
         ▼
┌─────────────────┐
│  Cached Token   │
│  (50 min TTL)   │
└─────────────────┘
```

## Testing Checklist

Before running OAuth tests:

- [ ] NoETL server and worker are running
- [ ] Test credentials are registered in database
- [ ] Service account has required IAM permissions
- [ ] GCP resources (secrets, buckets) exist
- [ ] Network connectivity to APIs

## Troubleshooting

### Common Issues

**Error: "Credential not found"**
```bash
# List registered credentials
curl http://localhost:8083/api/credentials | jq .

# Register credential
curl -X POST http://localhost:8083/api/credentials \
  -H 'Content-Type: application/json' \
  --data-binary @google_oauth.json
```

**Error: "403 Permission Denied"**
```bash
# Check service account permissions
gcloud projects get-iam-policy YOUR_PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:YOUR_SERVICE_ACCOUNT"

# Grant required role
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:YOUR_SERVICE_ACCOUNT" \
  --role="roles/secretmanager.secretAccessor"
```

**Error: "Invalid token"**
```bash
# Check worker logs
tail -f logs/worker.log | grep -i "token\|oauth"

# Verify credential structure
curl http://localhost:8083/api/credentials/google_oauth | jq '.data | keys'
```

### Debug Mode

Enable debug logging:

```bash
# Set log level
export NOETL_LOG_LEVEL=DEBUG

# Restart worker
noetl run automation/setup/worker-restart.yaml

# Watch logs
tail -f logs/worker-debug.log
```

## Next Steps

1. **Test with your own credentials**: Follow setup guides in each subdirectory
2. **Explore token caching**: Check logs to see token reuse
3. **Add custom providers**: Implement new `TokenProvider` subclasses
4. **Contribute**: Help implement IB OAuth or other providers

## Related Documentation

- [Token Auth Implementation](../../../../docs/token_auth_implementation.md)
- [Google Service Account Setup](../../../../docs/google_cloud_service_account.md)
- [Testing Token Auth](../../../../docs/testing_token_auth.md)
- [Credential Management](../../../../docs/credential_refactoring_summary.md)

## Support

For issues or questions:
1. Check README files in each test subdirectory
2. Review worker logs for detailed error messages
3. Consult documentation in `docs/` directory
4. Create an issue with debug logs and playbook YAML
