# Google ID Token Keychain Kind

This document describes the `google_id_token` keychain kind for generating Google Cloud ID tokens with auto-renewal support.

## Overview

The `google_id_token` keychain kind generates ID tokens for authenticating to Google Cloud Run services or other services that require Google ID tokens. It supports **two modes** for fetching service account credentials:

1. **Credential Table Mode** (Recommended): Fetches service account from NoETL's credential table
2. **Secret Manager Mode**: Fetches service account from Google Secret Manager

**Key Features:**
- Two flexible modes for service account retrieval
- Generates ID tokens with specified audience (target service URL)
- Supports auto-renewal (tokens expire after ~1 hour)
- Compatible with Bearer token authentication patterns
- Similar to `oauth2` keychain kind but specialized for Google Cloud ID tokens

## Use Case

This is ideal for authenticating to:
- Google Cloud Run services (requires ID token, not access token)
- Internal APIs protected by Google Cloud IAM
- Services using Google's Identity-Aware Proxy (IAP)

## Keychain Definitions

### Mode 1: Credential Table (Recommended)

**Simpler setup - no Secret Manager needed!**

```yaml
keychain:
  - name: cloud_run_id_token
    kind: google_id_token
    scope: global
    auto_renew: true
    service_account_credential: my_service_account  # Credential name in NoETL
    target_audience: https://my-service-abc123.run.app
```

### Mode 2: Secret Manager

**More secure - service account stored in Secret Manager**

```yaml
keychain:
  - name: cloud_run_id_token
    kind: google_id_token
    scope: global
    auto_renew: true
    auth: "{{ workload.gcp_auth }}"  # Credential for Secret Manager access
    service_account_secret: projects/123/secrets/my-service-account/versions/latest
    target_audience: https://my-service-abc123.run.app
```

## Required Fields

### Common Fields (Both Modes)

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Keychain entry name for reference in playbook |
| `kind` | string | Must be `google_id_token` |
| `target_audience` | string | Target audience for ID token (typically the service URL like `https://service.run.app`) |

### Mode 1: Credential Table

| Field | Type | Description |
|-------|------|-------------|
| `service_account_credential` | string | Name of credential in NoETL credential table containing service account JSON |

### Mode 2: Secret Manager

| Field | Type | Description |
|-------|------|-------------|
| `auth` | string | Reference to credential with Secret Manager access (typically `google_oauth` or `google_service_account` type) |
| `service_account_secret` | string | Full Secret Manager path to service account JSON (e.g., `projects/PROJECT_ID/secrets/SECRET_NAME/versions/VERSION`) |

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `scope` | string | `global` | Token scope: `global`, `catalog`, or `local` |
| `auto_renew` | boolean | `false` | Enable automatic token renewal when expired |
| `ttl_seconds` | integer | `3600` | Token time-to-live in seconds (default: 1 hour) |

## Usage in Playbook

### Mode 1: Credential Table (Recommended)

**Simplest approach - just reference the credential name:**

```yaml
apiVersion: noetl.io/v2
kind: Playbook

metadata:
  name: cloud_run_api_call_simple
  path: examples/cloud_run_api_simple

workload:
  service_url: https://my-service-abc123.run.app

keychain:
  - name: service_id_token
    kind: google_id_token
    scope: global
    auto_renew: true
    service_account_credential: my_service_account  # Must be registered in NoETL
    target_audience: "{{ workload.service_url }}"

workflow:
  - step: call_cloud_run_service
    desc: Call Cloud Run service with ID token
    tool:
      kind: http
      url: "{{ workload.service_url }}/api/endpoint"
      method: GET
      headers:
        Authorization: "Bearer {{ keychain.service_id_token.id_token }}"
    next:
      - step: end
```

### Mode 2: Secret Manager

**More secure - service account in Secret Manager:**

```yaml
apiVersion: noetl.io/v2
kind: Playbook

metadata:
  name: cloud_run_api_call_secure
  path: examples/cloud_run_api_secure

workload:
  gcp_auth: google_oauth
  service_url: https://my-service-abc123.run.app

keychain:
  - name: service_id_token
    kind: google_id_token
    scope: global
    auto_renew: true
    auth: "{{ workload.gcp_auth }}"
    service_account_secret: projects/123/secrets/my-sa/versions/latest
    target_audience: "{{ workload.service_url }}"

workflow:
  - step: call_cloud_run_service
    desc: Call Cloud Run service with ID token
    tool:
      kind: http
      url: "{{ workload.service_url }}/api/endpoint"
      method: GET
      headers:
        Authorization: "Bearer {{ keychain.service_id_token.id_token }}"
    next:
      - step: end
```

### Token Structure

The `google_id_token` keychain entry provides the following fields:

```yaml
keychain.service_id_token:
  id_token: "eyJhbGc..."          # The actual ID token (JWT)
  access_token: "eyJhbGc..."      # Alias of id_token for Bearer auth compatibility
  token_type: "Bearer"            # Token type for Authorization header
  audience: "https://service.run.app"  # Target audience
```

You can use either `id_token` or `access_token` - they contain the same value:

```yaml
# Both are equivalent:
Authorization: "Bearer {{ keychain.service_id_token.id_token }}"
Authorization: "Bearer {{ keychain.service_id_token.access_token }}"
```

## Setup Requirements

### Mode 1: Credential Table Setup

**Step 1: Create credential JSON file**

```json
{
  "name": "my_service_account",
  "type": "google_service_account",
  "description": "Service account for Cloud Run authentication",
  "tags": ["cloud-run", "id-token"],
  "data": {
    "type": "service_account",
    "project_id": "my-project",
    "private_key_id": "abc123...",
    "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
    "client_email": "my-sa@my-project.iam.gserviceaccount.com",
    "client_id": "123456789",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/..."
  }
}
```

**Step 2: Register credential in NoETL**

```bash
noetl catalog credentials register my_service_account.json
```

**That's it!** No Secret Manager setup needed.

### Mode 2: Secret Manager Setup

**Step 1: Store service account in Secret Manager**

```bash
# Create secret
gcloud secrets create my-service-account \
  --project=my-project \
  --replication-policy=automatic

# Upload service account JSON
gcloud secrets versions add my-service-account \
  --project=my-project \
  --data-file=service-account-key.json
```

The service account JSON should have this structure:

```json
{
  "type": "service_account",
  "project_id": "my-project",
  "private_key_id": "abc123...",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
  "client_email": "my-sa@my-project.iam.gserviceaccount.com",
  "client_id": "123456789",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/..."
}
```

**Step 2: Register NoETL credential for Secret Manager access**

```json
{
  "name": "google_oauth",
  "type": "google_oauth",
  "description": "Service account for accessing Secret Manager",
  "data": {
    "type": "service_account",
    "project_id": "my-project",
    "private_key_id": "...",
    "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
    "client_email": "secret-manager-reader@my-project.iam.gserviceaccount.com",
    ...
  }
}
```

Register it:

```bash
noetl catalog credentials register google_oauth_credential.json
```

**Step 3: Grant IAM permissions**

The service account used for Secret Manager access needs:

```bash
gcloud secrets add-iam-policy-binding my-service-account \
  --project=my-project \
  --member=serviceAccount:secret-manager-reader@my-project.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor
```

## Implementation Details

### How It Works

1. **Keychain Processing** (execution start):
   - NoETL fetches the auth credential from database
   - Generates an access token for Secret Manager API
   - Fetches the service account JSON from Secret Manager
   - Uses `google.oauth2.service_account.IDTokenCredentials` to generate ID token
   - Stores token in `noetl.keychain` table with expiration metadata

2. **Token Usage** (during execution):
   - Playbook references token via `{{ keychain.entry_name.id_token }}`
   - Worker resolves keychain reference from cached entry
   - Token is injected into HTTP headers or other contexts

3. **Auto-Renewal** (when enabled):
   - NoETL checks token expiration before each use
   - If expired, re-fetches service account and regenerates ID token
   - New token is cached with updated expiration

### Token Expiration

Google ID tokens typically expire after **1 hour**. With `auto_renew: true`, NoETL will automatically:
- Check token expiration before use
- Regenerate token if expired
- Cache new token for subsequent steps

### Comparison to OAuth2 Keychain

| Feature | `oauth2` | `google_id_token` |
|---------|----------|-------------------|
| Purpose | Generic OAuth2 client credentials flow | Google Cloud ID token generation |
| Token Type | Access token (varies by provider) | ID token (JWT with audience claim) |
| Renewal | HTTP POST to token endpoint | Re-generate from service account |
| Use Case | APIs with OAuth2 (Amadeus, Auth0, etc.) | Google Cloud Run, IAP-protected services |
| Credential Storage | Inline in keychain definition | In Google Secret Manager |

## Examples

### Example 1: Cloud Run Service (Credential Mode - Simplest)

```yaml
keychain:
  - name: my_service_token
    kind: google_id_token
    scope: global
    auto_renew: true
    service_account_credential: my_cloud_run_sa
    target_audience: https://my-service-abc.run.app

workflow:
  - step: fetch_data
    tool:
      kind: http
      url: https://my-service-abc.run.app/api/data
      headers:
        Authorization: "Bearer {{ keychain.my_service_token.id_token }}"
```

### Example 2: Cloud Run Service (Secret Manager Mode - Most Secure)

```yaml
keychain:
  - name: my_service_token
    kind: google_id_token
    scope: global
    auto_renew: true
    auth: google_oauth
    service_account_secret: projects/123/secrets/cloud-run-sa/versions/1
    target_audience: https://my-service-abc.run.app

workflow:
  - step: fetch_data
    tool:
      kind: http
      url: https://my-service-abc.run.app/api/data
      headers:
        Authorization: "Bearer {{ keychain.my_service_token.id_token }}"
```

### Example 3: Multiple Services (Credential Mode)

```yaml
keychain:
  # Service A token
  - name: service_a_token
    kind: google_id_token
    scope: global
    auto_renew: true
    service_account_credential: service_a_sa
    target_audience: https://service-a.run.app
  
  # Service B token
  - name: service_b_token
    kind: google_id_token
    scope: global
    auto_renew: true
    service_account_credential: service_b_sa
    target_audience: https://service-b.run.app

workflow:
  - step: call_service_a
    tool:
      kind: http
      url: https://service-a.run.app/api/endpoint
      headers:
        Authorization: "Bearer {{ keychain.service_a_token.id_token }}"
    next:
      - step: call_service_b
  
  - step: call_service_b
    tool:
      kind: http
      url: https://service-b.run.app/api/endpoint
      headers:
        Authorization: "Bearer {{ keychain.service_b_token.id_token }}"
```

## Which Mode to Use?

| Criterion | Credential Table | Secret Manager |
|-----------|------------------|----------------|
| **Setup Complexity** | ⭐⭐⭐ Simple | ⭐ Complex |
| **Security** | ⭐⭐ Good (encrypted in NoETL DB) | ⭐⭐⭐ Best (external secret store) |
| **Performance** | ⭐⭐⭐ Fast (one DB lookup) | ⭐⭐ Slower (two API calls) |
| **Dependencies** | None | Requires Secret Manager API access |
| **Best For** | Dev/test environments, simpler deployments | Production, compliance-heavy environments |
| **Cost** | Free | Secret Manager API costs |

**Recommendation**: Start with **Credential Table mode** for simplicity. Switch to Secret Manager if you need:
- Centralized secret management across multiple systems
- Audit logs for secret access
- Secret rotation managed externally
- Compliance requirements for secret storage

## Testing

Run the test playbook:

```bash
# Register credentials first
noetl catalog credentials register google_oauth_credential.json

# Register test playbook
noetl catalog playbooks register tests/fixtures/playbooks/keychain/google_id_token/google_id_token_test.yaml

# Execute test
noetl catalog playbooks execute tests/fixtures/playbooks/keychain/google_id_token
```

Check test results:

```sql
SELECT * FROM google_id_token_test_results ORDER BY created_at DESC;
```

## Troubleshooting

### Error: "Failed to fetch credential"

**Cause**: The `auth` credential is not registered or accessible.

**Solution**: Verify credential exists:
```bash
noetl catalog credentials list | grep google_oauth
```

### Error: "Empty payload for service account secret"

**Cause**: The Secret Manager path is incorrect or the secret doesn't exist.

**Solution**: Verify secret exists:
```bash
gcloud secrets versions access latest --secret=my-service-account --project=my-project
```

### Error: "Failed to obtain ID token from service account"

**Cause**: The service account JSON is invalid or missing required fields.

**Solution**: Validate service account JSON structure (must have `type`, `client_email`, `private_key`, etc.)

### Error: "401 Unauthorized" when calling service

**Cause**: The `target_audience` doesn't match the service URL, or the service account lacks IAM permissions.

**Solution**:
1. Verify `target_audience` exactly matches the service URL
2. Grant the service account `roles/run.invoker` on the Cloud Run service:
   ```bash
   gcloud run services add-iam-policy-binding my-service \
     --region=us-central1 \
     --member=serviceAccount:my-sa@project.iam.gserviceaccount.com \
     --role=roles/run.invoker
   ```

## Related Documentation

- [Google Cloud ID Tokens](https://cloud.google.com/docs/authentication/token-types#id)
- [Cloud Run Authentication](https://cloud.google.com/run/docs/authenticating/service-to-service)
- [NoETL Keychain Processor](../../noetl/server/keychain_processor.py)
- [OAuth2 Keychain Kind](../playbooks/api_integration/amadeus_ai_api/amadeus_ai_api.yaml)
