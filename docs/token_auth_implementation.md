# Token-Based Authentication Implementation

## Overview

Extend NoETL auth handling to support OAuth tokens and service account impersonation for various services (Snowflake, HTTP APIs, etc.) instead of relying on static credentials.

## Current State

### Existing Pattern (gcloud CLI-based)
```bash
gcloud auth print-identity-token \
  --impersonate-service-account={{.DEV_TOKEN_SERVICE_ACCOUNT}}
```

### Target Pattern (Python SDK-based)
```python
import google.auth.transport.requests
import google.oauth2.id_token

req = google.auth.transport.requests.Request()
aud = ""
token = google.oauth2.id_token.fetch_id_token(req, aud)
```

### HTTP Action with Token Injection
```yaml
tool: http
endpoint: "{{ workload.base_url }}/api/public/preview1/orgs/{{ workload.org_uuid }}/patients/{{ patient_id }}"
method: GET
timeout: 10
headers:
  Authorization: "Bearer {{ workload.bearer_token }}"
  x-customer-code: "{{ workload.customer_code }}"
assert:
  expects: [ patient_id ]
  returns: [ data ]
retry:
  max_attempts: 10
  initial_delay: 2.0
  backoff_multiplier: 2.0
  max_delay: 60.0
  jitter: true
  retry_when: "{{ this.data.status_code != 200 }}"
  stop_when: "{{ this.data.status_code in [400, 401, 403, 404] }}"
```

## Current State - Implementation Complete ✅

### What Was Implemented

**Phase 1-2: Core Token Infrastructure (✅ Complete)**
- Created `noetl/core/auth/` module with token provider abstraction
- Implemented `GoogleTokenProvider` for service account and OAuth tokens
- Added token caching and automatic refresh logic
- Registered `token()` function in Jinja2 environment for all playbooks
- Updated credential schema documentation with token-based types

**Phase 3: Snowflake Key-Pair Authentication (✅ Complete)**
- Updated `noetl/plugin/tools/snowflake/execution.py` to support RSA private keys
- Modified `noetl/plugin/tools/snowflake/auth.py` to extract key-pair parameters
- Added `cryptography` dependency for key parsing
- Created Snowflake key-pair auth documentation and examples

**Phase 4: HTTP Token Injection (✅ Complete)**
- Token resolution available via `{{ token('credential_name') }}` in all templates
- Supports ID tokens with audience: `{{ token('cred', 'https://example.com') }}`
- Works in HTTP headers, command parameters, and any Jinja2 context

### How to Use

**1. Google Service Account Tokens:**

Register credential:
```json
{
  "name": "google_sa",
  "type": "google_service_account",
  "data": {
    "type": "service_account",
    "project_id": "my-project",
    "private_key_id": "...",
    "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----",
    "client_email": "sa@my-project.iam.gserviceaccount.com",
    "client_id": "...",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token"
  }
}
```

Use in playbook:
```yaml
- step: call_api
  tool: http
  endpoint: "https://api.example.com/data"
  method: GET
  headers:
    Authorization: "Bearer {{ token('google_sa') }}"
```

**2. Snowflake Key-Pair Auth:**

Register credential:
```json
{
  "name": "sf_keypair",
  "type": "snowflake",
  "data": {
    "sf_account": "ACCOUNT-REGION",
    "sf_user": "USERNAME",
    "sf_private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----",
    "sf_warehouse": "WH_NAME",
    "sf_database": "DB_NAME",
    "sf_schema": "PUBLIC",
    "sf_role": "ROLE_NAME"
  }
}
```

Use in playbook:
```yaml
- step: query_snowflake
  tool: snowflake
  auth: sf_keypair
  command: |
    SELECT * FROM my_table;
```

**3. Google Service Account Impersonation:**

Register credential:
```json
{
  "name": "impersonate_sa",
  "type": "google_service_account",
  "data": {
    "impersonate_service_account": "target-sa@project.iam.gserviceaccount.com",
    "scopes": ["https://www.googleapis.com/auth/cloud-platform"],
    "lifetime": 3600
  }
}
```

Use in playbook:
```yaml
headers:
  Authorization: "Bearer {{ token('impersonate_sa', 'https://my-service.run.app') }}"
```

## Next Steps

### Immediate Testing

**1. Manual Validation:**
```bash
# Test compilation (no syntax errors)
cd /Users/kadyapam/projects/noetl/noetl
python -m py_compile noetl/core/auth/*.py
python -m py_compile noetl/plugin/tools/snowflake/*.py

# Install updated dependencies
pip install -e .

# Start worker and verify token function registration
# Check logs for: "Registered token resolution functions in Jinja environment"
```

**2. Snowflake Key-Pair Setup:**
```bash
# Follow guide: docs/snowflake_keypair_auth.md
# Generate keys, assign to Snowflake user, test connection

# Quick test:
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt
openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub

# In Snowflake:
# ALTER USER NOETL SET RSA_PUBLIC_KEY='<public_key_content>';
```

**3. Google Service Account Test:**
```bash
# Create/download service account key from GCP Console
# Register as credential
# Test token resolution in playbook
```

### Remaining Work

1. **Testing & Validation**
   - [ ] Test Google service account token resolution
   - [ ] Test Snowflake key-pair authentication
   - [ ] Create integration test suite
   - [ ] Validate token caching and refresh

2. **DuckDB Snowflake Integration**
   - [ ] Update `noetl/plugin/tools/duckdb/auth/secrets.py` to support key-pair
   - [ ] Test DuckDB → Snowflake queries with key-pair auth

3. **Documentation**
   - [x] Snowflake key-pair setup guide (see `docs/snowflake_keypair_auth.md`)
   - [ ] Google OAuth setup guide
   - [ ] Credential migration guide from password to token-based
   - [ ] Troubleshooting guide

4. **Production Readiness**
   - [ ] Add token refresh error handling
   - [ ] Implement token expiration warnings
   - [ ] Add metrics for token fetch failures
   - [ ] Security audit of credential storage

## Problem 1: Snowflake MFA/TOTP Requirement ✅ SOLVED

### Error
```
250001 (08001): Failed to connect to DB: NDCFGPC-MI21697.snowflakecomputing.com:443. 
Failed to authenticate: MFA with TOTP is required. To authenticate, provide both your 
password and a current TOTP passcode.
```

### Affected Files
- **Playbook**: `tests/fixtures/playbooks/data_transfer/snowflake_postgres/snowflake_postgres.yaml`
- **Credentials**: `tests/fixtures/credentials/sf_test.json`
- **Database**: `jdbc:postgresql://localhost:54321/demo_noetl`
  - User: `demo`
  - Password: `demo`
  - Table: `noetl.credential`

### Current Credential Format
Location: `tests/fixtures/credentials/sf_test.json`

### Solution Requirements

1. **Token Generation Support**
   - Implement OAuth token fetching using Google Auth SDK
   - Support service account impersonation
   - Handle token refresh and expiration

2. **Snowflake Authentication Modernization**
   - Replace password-based auth with OAuth tokens
   - Support Snowflake key-pair authentication
   - Handle MFA/TOTP requirements through OAuth flow

3. **Credential Schema Extension**
   - Add token-based credential types
   - Support service account credentials
   - Store OAuth client configs

4. **Plugin Updates**
   - Update HTTP plugin to inject dynamic tokens
   - Update Snowflake plugin to use token auth
   - Add token resolver/provider abstraction

## Implementation Tasks

### Phase 1: Token Provider Infrastructure ✅ COMPLETED
- [x] Create token provider abstraction in `noetl/core/auth/`
- [x] Implement Google OAuth token provider
- [x] Add token caching and refresh logic
- [x] Update credential schema to support token-based auth types

**Completed Files:**
- `noetl/core/auth/__init__.py` - Module exports
- `noetl/core/auth/providers.py` - TokenProvider base class and factory
- `noetl/core/auth/google_provider.py` - GoogleTokenProvider implementation
- `noetl/core/auth/token_resolver.py` - Jinja2 token() function
- `noetl/server/api/credential/schema.py` - Updated with token types

### Phase 2: Jinja2 Token Integration ✅ COMPLETED
- [x] Register token() function in worker Jinja environment
- [x] Enable {{ token('credential_name') }} in all playbook templates
- [x] Enable {{ token('credential_name', 'audience') }} for ID tokens

**Completed Files:**
- `noetl/worker/queue_worker.py` - Registered token functions

### Phase 3: Snowflake Key-Pair Authentication 🔄 IN PROGRESS
- [ ] Research Snowflake key-pair auth requirements
- [ ] Update Snowflake connector to support private_key parameter
- [ ] Update `noetl/plugin/tools/snowflake/execution.py` auth logic
- [ ] Create test credentials with RSA private key
- [ ] Update `tests/fixtures/credentials/sf_test.json` format
- [ ] Update DuckDB Snowflake secret generation for key-pair auth

**Snowflake Key-Pair Auth Details:**
Snowflake supports RSA key-pair authentication as alternative to passwords:
1. Generate RSA key pair (2048-bit minimum)
2. Assign public key to Snowflake user account
3. Connect using private key instead of password
4. No MFA/TOTP required with key-pair auth

**Required Credential Format:**
```json
{
  "name": "sf_test",
  "type": "snowflake",
  "data": {
    "sf_account": "NDCFGPC-MI21697",
    "sf_user": "NOETL",
    "sf_private_key": "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----",
    "sf_private_key_passphrase": "optional_passphrase",
    "sf_warehouse": "SNOWFLAKE_LEARNING_WH",
    "sf_database": "TEST_DB",
    "sf_schema": "PUBLIC",
    "sf_role": "ACCOUNTADMIN"
  }
}
```

### Phase 4: HTTP Plugin Token Injection ✅ COMPLETED
- [x] Token function available in templates
- [x] Support Bearer token auto-resolution via {{ token('cred') }}

**Usage Example:**
```yaml
tool: http
endpoint: "{{ workload.base_url }}/api/endpoint"
method: GET
headers:
  Authorization: "Bearer {{ token('google_sa_cred') }}"
  x-custom-header: "value"
```

### Phase 5: Testing & Documentation 📝 PENDING
- [ ] Create integration tests with token auth
- [ ] Test Google service account token resolution
- [ ] Test Snowflake key-pair authentication
- [ ] Update playbook examples with token patterns
- [ ] Document credential registration for token types
- [ ] Add troubleshooting guide for token auth

## Technical Considerations

### Token Resolution Flow
1. Playbook references credential by name
2. Server resolves credential type (password vs token)
3. If token-based, invoke appropriate provider
4. Cache token with TTL
5. Inject into plugin execution context

### Security Requirements
- Store service account keys securely
- Never log tokens in events or logs
- Use memory-only token cache
- Support credential rotation

### Backward Compatibility
- Maintain support for existing password-based credentials
- Add opt-in token auth via credential type field
- No breaking changes to existing playbooks

## Notes

- Add implementation details, code snippets, and design decisions as work progresses
- Document any breaking changes or migration steps
- Include examples of updated playbook patterns
