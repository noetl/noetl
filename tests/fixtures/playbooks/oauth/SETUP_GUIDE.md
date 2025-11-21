# OAuth Test Playbooks - Quick Setup Guide

Complete guide to set up and test OAuth authentication with Google services.

## Overview

Three OAuth test scenarios are ready:

1. ✅ **Google Secret Manager** - Access secrets using OAuth tokens
2. ✅ **Google Cloud Storage (GCS)** - List buckets, download objects  
3. 🚧 **Interactive Brokers** - Trading API (placeholder for future implementation)

## Quick Start (5 minutes)

### Step 1: Get Google Credentials

**Option A: Use Your Existing gcloud Credentials (Easiest!)**

If you already have gcloud configured:

```bash
# Check your setup
gcloud config get-value project  # Get your project ID
cat ~/.config/gcloud/configurations/config_default

# Copy credentials to NoETL format
cd /path/to/noetl
./tests/fixtures/credentials/copy_gcloud_credentials.sh

# ✅ Done! Skip to Step 2
```

**Option B: Create New Service Account**

If you need a dedicated service account:

```bash
# Set your project ID
export PROJECT_ID="your-project-id"

# Create service account
gcloud iam service-accounts create noetl-oauth-test \
  --project=$PROJECT_ID \
  --display-name="NoETL OAuth Test"

# Download service account key
gcloud iam service-accounts keys create google_oauth.json \
  --project=$PROJECT_ID \
  --iam-account="noetl-oauth-test@${PROJECT_ID}.iam.gserviceaccount.com"

# Wrap in NoETL format
cat > tests/fixtures/credentials/google_oauth.json << 'EOF'
{
  "name": "google_oauth",
  "type": "google_oauth",
  "description": "Service account for OAuth testing",
  "tags": ["oauth", "google", "test"],
  "data": <PASTE_SERVICE_ACCOUNT_JSON_HERE>
}
EOF
```

### Step 2: Grant Required Permissions

**Get your project ID first**:
```bash
export PROJECT_ID=$(gcloud config get-value project)
echo "Using project: $PROJECT_ID"
```

For **Secret Manager** test:
```bash
# Verify the secret exists (using gcs_hmac_local which is already in Secret Manager)
gcloud secrets describe gcs_hmac_local --project=$PROJECT_ID

# Grant access
# If using user credentials (Option A):
gcloud secrets add-iam-policy-binding gcs_hmac_local \
  --project=$PROJECT_ID \
  --member="user:your-email@gmail.com" \
  --role="roles/secretmanager.secretAccessor"

# If using service account (Option B):
gcloud secrets add-iam-policy-binding gcs_hmac_local \
  --project=$PROJECT_ID \
  --member="serviceAccount:noetl-oauth-test@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

For **GCS** test:
```bash
# Verify you can list buckets (test only needs list permission)
gsutil ls -p $PROJECT_ID | head -5

# Grant access (if using service account Option B):
# User credentials (Option A) already have access! ✅
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:noetl-oauth-test@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"

echo "✅ GCS test ready - no objects needed, test only lists buckets"
```

### Step 3: Register Credential with NoETL

```bash
# Start NoETL (if not already running)
task noetl:local:start

# Register credential
curl -X POST http://localhost:8083/api/credentials \
  -H 'Content-Type: application/json' \
  --data-binary @tests/fixtures/credentials/google_oauth.json

# Verify registration
curl http://localhost:8083/api/credentials/google_oauth | jq .
```

### Step 4: Update Playbook Configuration

Edit playbook workload section with your values:

**Secret Manager** (`google_secret_manager/google_secret_manager.yaml`):
```yaml
workload:
  google_auth: google_oauth              # Keep this (credential name)
  project_id: noetl-demo-19700101        # ← Change to your PROJECT_ID
  secret_name: gcs_hmac_local            # Keep this (secret exists in Secret Manager)
  version: latest                        # Keep this
```

**Get your project ID**:
```bash
gcloud config get-value project
# Or: cat ~/.config/gcloud/configurations/config_default
```

**GCS** (`google_gcs/google_gcs_oauth.yaml`):
```yaml
workload:
  google_auth: google_oauth              # Keep this (credential name)
  project_id: noetl-demo-19700101        # ← Change to your PROJECT_ID
  bucket_name: noetl-demo-19700101       # Usually matches project ID
  object_path: fixture/test_oauth.json   # Not used (test only lists buckets)
```

### Step 5: Run Tests

```bash
# Test Secret Manager
.venv/bin/noetl execute playbook \
  "tests/fixtures/playbooks/oauth/google_secret_manager" \
  --host localhost --port 8083

# Test GCS
.venv/bin/noetl execute playbook \
  "tests/fixtures/playbooks/oauth/google_gcs" \
  --host localhost --port 8083
```

## Expected Results

### Secret Manager Test Success

```json
{
  "status": "success",
  "message": "OAuth token authentication successful!",
  "secret_retrieved": true,
  "secret_length": 25,
  "validation": "Token was generated, API call succeeded, secret decoded"
}
```

### GCS Test Success

```json
{
  "status": "success",
  "message": "GCS OAuth authentication fully verified!",
  "bucket_listing": "SUCCESS",
  "buckets_found": 5,
  "validation": "Token generated, GCS API calls succeeded"
}
```

## Troubleshooting

### Error: "403 Permission Denied"

**Cause**: Service account lacks IAM permissions

**Fix**:
```bash
# For Secret Manager
gcloud secrets add-iam-policy-binding test_secret \
  --project=$PROJECT_ID \
  --member="serviceAccount:noetl-oauth-test@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# For GCS
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:noetl-oauth-test@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"
```

### Error: "404 Not Found"

**Cause**: Resource doesn't exist

**Fix**:
```bash
# Verify secret exists
gcloud secrets list --project=$PROJECT_ID

# Verify bucket exists
gsutil ls -p $PROJECT_ID

# Verify object exists
gsutil ls -r gs://$BUCKET_NAME/
```

### Error: "Credential not found"

**Cause**: Credential not registered in NoETL

**Fix**:
```bash
# List registered credentials
curl http://localhost:8083/api/credentials

# Register if missing
curl -X POST http://localhost:8083/api/credentials \
  -H 'Content-Type: application/json' \
  --data-binary @tests/fixtures/credentials/google_oauth.json
```

### Error: "Invalid token"

**Cause**: Service account key is invalid or expired

**Fix**:
```bash
# Verify JSON structure
cat tests/fixtures/credentials/google_oauth.json | jq .

# Test with gcloud
gcloud auth activate-service-account \
  --key-file=tests/fixtures/credentials/google_oauth.json

# List secrets to verify auth works
gcloud secrets list --project=$PROJECT_ID
```

## How It Works

### Token Generation Flow

```
1. Playbook uses: {{ token('google_oauth', 'https://secretmanager.googleapis.com/') }}
2. Worker resolves template during execution
3. Fetches 'google_oauth' credential from encrypted database
4. Instantiates GoogleTokenProvider with credential data
5. Generates ID token with specified audience
6. Caches token for ~50 minutes
7. Injects token into HTTP Authorization header
8. API call succeeds with Bearer token
```

### Architecture

```
Playbook YAML
    ↓
{{ token(credential, audience) }} ← Jinja2 template
    ↓
Token Resolver (worker/context.py)
    ↓
Credential Fetch (encrypted DB)
    ↓
GoogleTokenProvider (google_provider.py)
    ↓
google.auth.transport.requests ← Python SDK
    ↓
ID Token (JWT, ~1 hour expiry)
    ↓
HTTP Authorization: Bearer <token>
```

## Using Regular vs Impersonation Account

### Regular Service Account

**Use when**: You have a dedicated service account with direct permissions

**Setup**: Just download the service account key JSON

**Playbook**: Use `google_oauth.json` credential

**Example**:
```json
{
  "name": "google_oauth",
  "type": "google_oauth",
  "data": {
    "type": "service_account",
    "project_id": "your-project-id",
    "private_key": "-----BEGIN PRIVATE KEY-----\n...",
    "client_email": "sa@project.iam.gserviceaccount.com"
  }
}
```

### Impersonation Account

**Use when**: You want to impersonate another service account with different permissions

**Setup**: 
1. Create source service account (the impersonator)
2. Grant it `roles/iam.serviceAccountTokenCreator` on target service account
3. Use `google_oauth_impersonate.json` credential

**Playbook**: Use `google_oauth_impersonate` credential

**Example**:
```json
{
  "name": "google_oauth_impersonate",
  "type": "google_oauth",
  "data": {
    "impersonate_service_account": "target@project.iam.gserviceaccount.com",
    "source_credentials": {
      "type": "service_account",
      "project_id": "your-project-id",
      "private_key": "-----BEGIN PRIVATE KEY-----\n...",
      "client_email": "source@project.iam.gserviceaccount.com"
    }
  }
}
```

**When to use impersonation**:
- CI/CD pipelines with different permission levels
- Cross-project access
- Temporary elevated permissions
- Audit trail (shows impersonation in logs)

**For these tests, use regular service account** - it's simpler and sufficient.

## Next Steps

1. **Test with your data**: Modify playbooks to access your actual secrets/buckets
2. **Extend to other Google APIs**: Add BigQuery, Cloud SQL, etc.
3. **Implement Interactive Brokers**: Help us build IB OAuth support!
4. **Create custom playbooks**: Use OAuth credentials in your own workflows

## Resources

- [Main OAuth README](./README.md) - Detailed documentation
- [Secret Manager Test](./google_secret_manager/README.md)
- [GCS Test](./google_gcs/README.md)
- [Token Auth Implementation](../../../../docs/token_auth_implementation.md)
- [Google Service Account Guide](../../../../docs/google_cloud_service_account.md)

## Support

Questions or issues? Check:
1. Individual test README files for specific guidance
2. Worker logs: `tail -f logs/worker.log | grep -i token`
3. Credential status: `curl http://localhost:8083/api/credentials/google_oauth`
