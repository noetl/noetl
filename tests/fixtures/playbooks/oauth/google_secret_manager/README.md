# Google Secret Manager OAuth Test

This playbook tests OAuth token-based authentication with Google Secret Manager API.

## What This Tests

1. **Token Generation**: Uses the `token()` Jinja2 function to generate OAuth access tokens from Google credentials
2. **API Authentication**: Calls Secret Manager API with `Bearer` token in Authorization header
3. **Secret Retrieval**: Accesses a secret from Google Secret Manager
4. **Base64 Decoding**: Decodes the secret payload
5. **End-to-End Validation**: Verifies the entire OAuth flow works

**Note**: Secret Manager API requires OAuth 2.0 access tokens (with scopes), not ID tokens. The `token()` function without an audience parameter generates access tokens.

## Prerequisites

### Option A: Use Your Existing gcloud Credentials (Recommended for Local Testing)

If you already have gcloud configured locally, this is the simplest approach:

```bash
# 1. Check your gcloud configuration
cat ~/.config/gcloud/configurations/config_default
# Note your project ID (e.g., noetl-demo-19700101)

# 2. Copy your existing credentials to NoETL format
cd /path/to/noetl
./tests/fixtures/credentials/copy_gcloud_credentials.sh

# This creates: tests/fixtures/credentials/google_oauth.json
# Using your OAuth user credentials from ~/.config/gcloud/
```

### Option B: Download New Service Account Key (For Production)

If you need a dedicated service account:

```bash
# Set your project
export PROJECT_ID="your-project-id"

# Create service account
gcloud iam service-accounts create noetl-oauth-test \
  --project=$PROJECT_ID \
  --display-name="NoETL OAuth Test"

# Download service account key
gcloud iam service-accounts keys create google_oauth.json \
  --project=$PROJECT_ID \
  --iam-account="noetl-oauth-test@${PROJECT_ID}.iam.gserviceaccount.com"

# Move to credentials directory
mv google_oauth.json tests/fixtures/credentials/

# Wrap in NoETL credential format
cat > tests/fixtures/credentials/google_oauth.json << 'EOF'
{
  "name": "google_oauth",
  "type": "google_oauth",
  "description": "Service account for NoETL OAuth testing",
  "tags": ["oauth", "google", "test"],
  "data": <PASTE_YOUR_SERVICE_ACCOUNT_JSON_HERE>
}
EOF
```

### 1. GCP Setup

```bash
# Get your project ID from gcloud config
export PROJECT_ID=$(gcloud config get-value project)
# Or set it manually: export PROJECT_ID="your-project-id"

# Verify the secret exists (using gcs_hmac_local which is already in Secret Manager)
gcloud secrets describe gcs_hmac_local --project=$PROJECT_ID

# Or create a new test secret if needed
echo -n "test-secret-value-$(date +%s)" | \
  gcloud secrets create test_secret \
  --project=$PROJECT_ID \
  --data-file=- \
  --replication-policy="automatic"
```

### 2. Grant Access

**If using your user credentials (Option A)**:
```bash
# Grant yourself access (usually already have it as project owner)
gcloud secrets add-iam-policy-binding gcs_hmac_local \
  --project=$PROJECT_ID \
  --member="user:your-email@gmail.com" \
  --role="roles/secretmanager.secretAccessor"
```

**If using service account (Option B)**:
```bash
# Grant service account access
gcloud secrets add-iam-policy-binding gcs_hmac_local \
  --project=$PROJECT_ID \
  --member="serviceAccount:noetl-oauth-test@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### 3. Register Credential with NoETL

```bash
# Register with NoETL
curl -X POST http://localhost:8083/api/credentials \
  -H 'Content-Type: application/json' \
  --data-binary @tests/fixtures/credentials/google_oauth.json

# Verify registration
curl http://localhost:8083/api/credentials/google_oauth
```

## Understanding Credential Types

NoETL supports both OAuth user credentials and service account credentials:

| Type | Source | Best For | Format |
|------|--------|----------|--------|
| **User Credentials** | `gcloud auth login` | Local development, testing | `{"type": "authorized_user", "client_id": "...", "refresh_token": "..."}` |
| **Service Account** | Downloaded JSON key | Production, CI/CD | `{"type": "service_account", "private_key": "...", "client_email": "..."}` |

**What you created**:
- If you ran `copy_gcloud_credentials.sh`: **User credentials** (simpler for testing)
- If you downloaded a service account key: **Service account** (better for production)

Both work identically in NoETL! The token provider detects the type automatically.

## Configuration

Edit the `workload` section in `google_secret_manager.yaml`:

```yaml
workload:
  google_auth: google_oauth          # Credential name in NoETL
  project_id: noetl-demo-19700101    # Your GCP project ID (from gcloud config)
  secret_name: gcs_hmac_local        # Secret name in Secret Manager (already exists)
  version: latest                    # Secret version (or specific version number)
```

**To get your project ID**:
```bash
gcloud config get-value project
# Or check: cat ~/.config/gcloud/configurations/config_default
```

## Execution

```bash
# Start NoETL
noetl server start

# Execute playbook
.venv/bin/noetl execute playbook \
  "tests/fixtures/playbooks/oauth/google_secret_manager" \
  --host localhost \
  --port 8083

# Or with custom parameters
.venv/bin/noetl execute playbook \
  "tests/fixtures/playbooks/oauth/google_secret_manager" \
  --host localhost \
  --port 8083 \
  --payload '{"project_id": "my-project", "secret_name": "my-secret"}' \
  --merge
```

## Expected Output

Successful execution should show:

```json
{
  "status": "success",
  "message": "OAuth token authentication successful!",
  "secret_retrieved": true,
  "secret_length": 25,
  "validation": "Token was generated, API call succeeded, secret decoded"
}
```

## How Token Generation Works

The playbook uses the `token()` function in Jinja2 templates:

```yaml
headers:
  Authorization: "Bearer {{ token(workload.google_auth, 'https://secretmanager.googleapis.com/') }}"
```

**Parameters**:
- `workload.google_auth`: Credential name (resolves to "google_oauth")
- `'https://secretmanager.googleapis.com/'`: Audience for the token

**What happens**:
1. NoETL fetches the credential from the database
2. Decrypts the credential data
3. Uses `GoogleTokenProvider` to generate an ID token with the specified audience
4. Token is cached for ~50 minutes
5. Token is injected into the HTTP Authorization header

## Troubleshooting

### Error: "403 Permission Denied"

- Verify service account has `roles/secretmanager.secretAccessor` on the secret
- Check IAM permissions: `gcloud secrets get-iam-policy test_secret --project=$PROJECT_ID`

### Error: "404 Not Found"

- Verify secret exists: `gcloud secrets list --project=$PROJECT_ID`
- Check secret name matches: `gcloud secrets versions access latest --secret=test_secret --project=$PROJECT_ID`

### Error: "Invalid token"

- Verify credential is registered: `curl http://localhost:8083/api/credentials/google_oauth`
- Check service account key is valid and not expired
- Verify `private_key` has proper `\n` escaping in JSON

### Debug Token Generation

Check worker logs for token generation:

```bash
tail -f logs/worker.log | grep -i "token\|oauth\|google"
```

## Related Documentation

- [Token Auth Implementation](../../../../../docs/token_auth_implementation.md)
- [Google Service Account Setup](../../../../../docs/google_cloud_service_account.md)
- [Testing Token Auth](../../../../../docs/testing_token_auth.md)
