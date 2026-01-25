# Google Cloud Storage (GCS) OAuth Test

This playbook tests OAuth token-based authentication with Google Cloud Storage API.

## What This Tests

1. **Token Generation**: Generates OAuth access tokens from Google service account
2. **Bucket Listing**: Lists GCS buckets to verify authentication
3. **OAuth Validation**: Confirms token-based authentication works

**Note**: This test focuses on OAuth token authentication by listing buckets. No objects need to exist - bucket listing alone proves OAuth is working correctly.

## Prerequisites

### Option A: Use Your Existing gcloud Credentials (Recommended for Local Testing)

If you already have gcloud configured locally:

```bash
# 1. Check your gcloud configuration
export PROJECT_ID=$(gcloud config get-value project)
echo "Using project: $PROJECT_ID"

# 2. Copy your existing credentials to NoETL format
cd /path/to/noetl
./tests/fixtures/credentials/copy_gcloud_credentials.sh

# This creates: tests/fixtures/credentials/google_oauth.json
# Using your OAuth user credentials from ~/.config/gcloud/
```

### Option B: Download New Service Account Key (For Production)

If you need a dedicated service account:

```bash
# Create service account
gcloud iam service-accounts create noetl-gcs-test \
  --project=$PROJECT_ID \
  --display-name="NoETL GCS OAuth Test"

# Grant GCS read access (project-level)
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:noetl-gcs-test@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"

# Download service account key
gcloud iam service-accounts keys create google_oauth.json \
  --project=$PROJECT_ID \
  --iam-account="noetl-gcs-test@${PROJECT_ID}.iam.gserviceaccount.com"

# Wrap in NoETL credential format
cat > tests/fixtures/credentials/google_oauth.json << 'EOF'
{
  "name": "google_oauth",
  "type": "google_oauth",
  "description": "Service account for GCS OAuth testing",
  "tags": ["oauth", "google", "gcs", "test"],
  "data": <PASTE_YOUR_SERVICE_ACCOUNT_JSON_HERE>
}
EOF
```

### 1. GCS Setup

```bash
# Get your project ID
export PROJECT_ID=$(gcloud config get-value project)
echo "Using project: $PROJECT_ID"

# Verify you have at least one bucket (or the project bucket exists)
gsutil ls -p $PROJECT_ID | head -5

# If no buckets exist, create one (optional - test works without objects)
export BUCKET_NAME="$PROJECT_ID"  # Using project ID as bucket name (common pattern)
if ! gsutil ls -b gs://$BUCKET_NAME &>/dev/null; then
  gsutil mb -p $PROJECT_ID gs://$BUCKET_NAME
  echo "Created bucket: $BUCKET_NAME"
else
  echo "Bucket already exists: $BUCKET_NAME"
fi
```

### 2. Grant Access

**If using your user credentials (Option A)**:
```bash
# You already have access as project owner - no additional setup needed!
echo "Using user credentials - access already granted"
```

**If using service account (Option B)**:
```bash
# Grant bucket-specific access
gsutil iam ch \
  serviceAccount:noetl-gcs-test@${PROJECT_ID}.iam.gserviceaccount.com:objectViewer \
  gs://$BUCKET_NAME
```

### 3. Register Credential with NoETL

```bash
# Register with NoETL
curl -X POST http://localhost:8083/api/credentials \
  -H 'Content-Type: application/json' \
  --data-binary @tests/fixtures/credentials/google_oauth.json

# Verify registration
curl http://localhost:8083/api/credentials/google_oauth | jq .
```

## Configuration

Edit the `workload` section in `google_gcs_oauth.yaml`:

```yaml
workload:
  google_auth: google_oauth          # Credential name in NoETL
  project_id: noetl-demo-19700101    # Your GCP project (from gcloud config)
  bucket_name: noetl-demo-19700101   # Bucket name (commonly matches project ID)
  object_path: fixture/test_oauth.json  # Not used - test only lists buckets
```

**To get your project ID**:
```bash
# Get project ID
gcloud config get-value project

# Verify you can list buckets (proves OAuth will work)
gsutil ls -p $(gcloud config get-value project)
```

## Execution

```bash
# Start NoETL
noetl server start

# Execute playbook
.venv/bin/noetl execute playbook \
  "tests/fixtures/playbooks/oauth/google_gcs" \
  --host localhost \
  --port 8083

# With custom parameters
.venv/bin/noetl execute playbook \
  "tests/fixtures/playbooks/oauth/google_gcs" \
  --host localhost \
  --port 8083 \
  --payload '{"bucket_name": "my-bucket", "object_path": "my/file.json"}' \
  --merge
```

## Expected Output

Successful execution should show:

```json
{
  "status": "success",
  "message": "GCS OAuth authentication fully verified!",
  "bucket_listing": "SUCCESS",
  "buckets_found": 5,
  "validation": "Token generated, GCS API calls succeeded"
}
```

## OAuth Scopes

The playbook uses OAuth access tokens with default GCS scopes:

```yaml
headers:
  Authorization: "Bearer {{ token(workload.google_auth) }}"
```

**Note**: The `token()` function without an audience parameter generates an access token with the service account's default scopes, which includes GCS access.

**Available GCS scopes** (if you need to specify explicitly):
- `https://www.googleapis.com/auth/devstorage.read_only` - Read-only access
- `https://www.googleapis.com/auth/devstorage.read_write` - Read/write access
- `https://www.googleapis.com/auth/devstorage.full_control` - Full control

## API Endpoints Used

1. **List Buckets**: `GET https://storage.googleapis.com/storage/v1/b?project=PROJECT_ID`

This single endpoint is sufficient to verify OAuth token authentication is working correctly.

## Troubleshooting

### Error: "403 Forbidden"

```bash
# Check service account has correct role
gcloud projects get-iam-policy $PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:noetl-gcs-test@*"

# Grant storage.objectViewer role
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:noetl-gcs-test@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"
```

### Error: "404 Not Found" for bucket

```bash
# Verify bucket exists
gsutil ls -p $PROJECT_ID

# Create if missing
gsutil mb -p $PROJECT_ID gs://$BUCKET_NAME
```

### Error: "404 Not Found" for object

This is actually OK for the test! The playbook handles this gracefully and still verifies OAuth authentication worked.

To create the test object:

```bash
echo '{"test": "data"}' | gsutil cp - gs://$BUCKET_NAME/test/sample.json
```

### Debug Token Issues

```bash
# Check worker logs
tail -f logs/worker.log | grep -i "token\|gcs\|storage"

# Verify credential is registered
curl http://localhost:8083/api/credentials/google_oauth | jq .

# Test gcloud auth
gcloud auth activate-service-account --key-file=google_oauth.json
gsutil ls -p $PROJECT_ID
```

## Integration with DuckDB

This OAuth credential can also be used with DuckDB for GCS access:

```yaml
- step: query_gcs_with_duckdb
  tool: duckdb
  auth: "{{ workload.google_auth }}"
  command: |
    SELECT * FROM read_parquet('gs://{{ workload.bucket_name }}/data/*.parquet')
    LIMIT 10;
```

See `tests/fixtures/playbooks/duckdb_gcs/` for examples.

## Related Documentation

- [GCS OAuth Documentation](https://cloud.google.com/storage/docs/authentication)
- [Token Auth Implementation](../../../../../docs/token_auth_implementation.md)
- [Google Service Account Setup](../../../../../docs/google_cloud_service_account.md)
