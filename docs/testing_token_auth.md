# Testing Token-Based Authentication - Step-by-Step Guide

## Overview

This guide walks through testing the new token-based authentication features, specifically for Snowflake key-pair auth and Google OAuth tokens.

## Test Playbook

**Primary Test**: `tests/fixtures/playbooks/data_transfer/snowflake_postgres/snowflake_postgres.yaml`

This playbook is perfect for testing because it:
- Uses Snowflake authentication via `sf_test` credential
- Performs actual Snowflake operations (CREATE DATABASE, tables, INSERT, SELECT)
- Transfers data between Snowflake and PostgreSQL
- Validates data integrity

## Prerequisites

1. **Running NoETL Environment**:
   ```bash
   # Ensure Kubernetes cluster is running
   task kind-create-cluster
   task bring-all
   
   # Verify services are healthy
   task test-cluster-health
   ```

2. **PostgreSQL Credential** (already exists):
   ```bash
   # pg_local credential should be registered
   # Location: tests/fixtures/credentials/pg_local.json
   ```

## Option 1: Test with Password (Baseline - Will Fail with MFA)

**Purpose**: Confirm that password auth fails with MFA error

```bash
# Register existing password-based credential
curl -X POST http://localhost:8082/api/credentials \
  -H 'Content-Type: application/json' \
  --data-binary @tests/fixtures/credentials/sf_test.json

# Try to execute playbook (should fail with MFA error)
.venv/bin/noetl execute playbook "tests/fixtures/playbooks/data_transfer/snowflake_postgres" \
  --host localhost --port 8082 --json
```

**Expected Error**:
```
250001 (08001): Failed to connect to DB: NDCFGPC-MI21697.snowflakecomputing.com:443. 
Failed to authenticate: MFA with TOTP is required. To authenticate, provide both your 
password and a current TOTP passcode.
```

## Option 2: Test with Key-Pair Authentication (New Implementation)

### Step 1: Generate RSA Key Pair

```bash
# Navigate to test fixtures directory
cd tests/fixtures/credentials

# Generate 2048-bit RSA key (no passphrase for testing)
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out sf_rsa_key.p8 -nocrypt

# Extract public key
openssl rsa -in sf_rsa_key.p8 -pubout -out sf_rsa_key.pub

# Display private key (for credential JSON)
cat sf_rsa_key.p8

# Display public key (for Snowflake)
cat sf_rsa_key.pub
```

### Step 2: Assign Public Key to Snowflake User

**Connect to Snowflake** (via web UI or SnowSQL):

```sql
-- Remove header/footer and join into single line
-- From: -----BEGIN PUBLIC KEY-----
--       MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...
--       ...
--       -----END PUBLIC KEY-----
-- To: MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...

-- Assign public key to user
ALTER USER NOETL SET RSA_PUBLIC_KEY='MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...';

-- Verify key was set
DESC USER NOETL;

-- Expected output should show RSA_PUBLIC_KEY_FP (fingerprint)
```

### Step 3: Create Key-Pair Credential File

```bash
cd tests/fixtures/credentials

# Create new credential file
cat > sf_test.json << 'EOF'
{
  "name": "sf_test",
  "type": "snowflake",
  "description": "Snowflake key-pair authentication for tests",
  "tags": ["test", "snowflake", "keypair"],
  "data": {
    "sf_account": "NDCFGPC-MI21697",
    "sf_user": "NOETL",
    "sf_private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC...\n...\n-----END PRIVATE KEY-----",
    "sf_warehouse": "SNOWFLAKE_LEARNING_WH",
    "sf_database": "TEST_DB",
    "sf_schema": "PUBLIC",
    "sf_role": "ACCOUNTADMIN"
  }
}
EOF

# IMPORTANT: Replace the sf_private_key value with your actual private key
# Preserve the -----BEGIN/END PRIVATE KEY----- headers
# Replace actual newlines with \n in the JSON string
```

**Alternative - Using sed to create JSON from key file**:
```bash
# Read private key and format for JSON
PRIVATE_KEY=$(cat sf_rsa_key.p8 | sed ':a;N;$!ba;s/\n/\\n/g')

# Create credential file with key embedded
cat > sf_test.json << EOF
{
  "name": "sf_test",
  "type": "snowflake",
  "description": "Snowflake key-pair authentication for tests",
  "tags": ["test", "snowflake", "keypair"],
  "data": {
    "sf_account": "NDCFGPC-MI21697",
    "sf_user": "NOETL",
    "sf_private_key": "${PRIVATE_KEY}",
    "sf_warehouse": "SNOWFLAKE_LEARNING_WH",
    "sf_database": "TEST_DB",
    "sf_schema": "PUBLIC",
    "sf_role": "ACCOUNTADMIN"
  }
}
EOF
```

### Step 4: Register Key-Pair Credential

```bash
# Register the updated credential
curl -X POST http://localhost:8082/api/credentials \
  -H 'Content-Type: application/json' \
  --data-binary @tests/fixtures/credentials/sf_test.json | jq .

# Expected output:
# {
#   "id": "...",
#   "name": "sf_test",
#   "type": "snowflake",
#   "created_at": "...",
#   "updated_at": "..."
# }

# Verify credential is registered
curl -sS http://localhost:8082/api/credentials/sf_test | jq .
```

### Step 5: Execute Test Playbook

```bash
cd /Users/kadyapam/projects/noetl/noetl

# Execute the Snowflake → PostgreSQL transfer playbook
.venv/bin/noetl execute playbook "tests/fixtures/playbooks/data_transfer/snowflake_postgres" \
  --host localhost --port 8082 --json | jq .

# Alternative: Use task if available
task test:k8s:register-credentials  # Registers all test credentials
task test:k8s:register-playbooks     # Registers all test playbooks

# Then execute via catalog
curl -X POST http://localhost:8082/api/catalog/tests/fixtures/playbooks/data_transfer/snowflake_postgres/execute | jq .
```

### Step 6: Monitor Execution

```bash
# Get execution ID from response
EXECUTION_ID="<execution_id_from_response>"

# Monitor execution progress
curl -sS "http://localhost:8082/api/execution/${EXECUTION_ID}" | jq .

# Check execution events
curl -sS "http://localhost:8082/api/execution/${EXECUTION_ID}/events" | jq .

# Watch logs in real-time
kubectl logs -f deployment/noetl-worker -n noetl --tail=50

# Look for these log messages:
# - "Using key-pair authentication for Snowflake account"
# - "Private key successfully parsed and converted to DER format"
# - "Successfully connected to Snowflake"
```

### Step 7: Verify Results

```bash
# Get final execution status
curl -sS "http://localhost:8082/api/execution/${EXECUTION_ID}" | jq '.status'

# Expected: "success"

# Check final event
curl -sS "http://localhost:8082/api/execution/${EXECUTION_ID}/events" \
  | jq '.[] | select(.event_type == "workflow_complete")'

# Verify data in PostgreSQL
kubectl exec -it deployment/postgres -n noetl -- psql -U demo -d demo_noetl -c \
  "SELECT COUNT(*) FROM public.test_data_transfer;"

# Expected: 5 rows
```

## Option 3: Test Google OAuth Token Resolution (HTTP APIs)

### Step 1: Create Test Service Account

```bash
# In Google Cloud Console:
# 1. Go to IAM & Admin → Service Accounts
# 2. Create service account "noetl-test-sa"
# 3. Grant Cloud Run Invoker role (or appropriate permissions)
# 4. Create JSON key and download

# Save the key as:
# tests/fixtures/credentials/google_sa_test.json
```

### Step 2: Register Google Credential

```json
{
  "name": "google_sa_test",
  "type": "google_service_account",
  "description": "Google service account for token testing",
  "tags": ["test", "google", "oauth"],
  "data": {
    "type": "service_account",
    "project_id": "your-project-id",
    "private_key_id": "...",
    "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----",
    "client_email": "noetl-test-sa@your-project.iam.gserviceaccount.com",
    "client_id": "...",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "..."
  }
}
```

```bash
curl -X POST http://localhost:8082/api/credentials \
  -H 'Content-Type: application/json' \
  --data-binary @tests/fixtures/credentials/google_sa_test.json | jq .
```

### Step 3: Create Test Playbook with Token Function

```yaml
# tests/fixtures/playbooks/test_google_token.yaml
apiVersion: noetl.io/v1
kind: Playbook

metadata:
  name: test_google_token_resolution
  path: tests/fixtures/playbooks/test_google_token

workflow:
  - step: start
    desc: Test Google token resolution
    next:
      - step: test_access_token

  - step: test_access_token
    desc: Test access token fetch
    tool: http
    endpoint: "https://www.googleapis.com/oauth2/v1/tokeninfo"
    method: GET
    params:
      access_token: "{{ token('google_sa_test') }}"
    next:
      - step: test_id_token

  - step: test_id_token
    desc: Test ID token fetch with audience
    tool: http
    endpoint: "https://your-service-xyz.run.app/api/test"
    method: GET
    headers:
      Authorization: "Bearer {{ token('google_sa_test', 'https://your-service-xyz.run.app') }}"
    next:
      - step: end

  - step: end
    desc: Token tests completed
```

### Step 4: Execute Token Test

```bash
# Register and execute
curl -X POST http://localhost:8082/api/catalog/register \
  -H 'Content-Type: application/json' \
  -d @tests/fixtures/playbooks/test_google_token.yaml

curl -X POST http://localhost:8082/api/catalog/tests/fixtures/playbooks/test_google_token/execute | jq .

# Check logs for:
# - "Resolving token for credential: google_sa_test"
# - "Token resolved successfully for credential: google_sa_test"
# - "Google token fetched and cached successfully"
```

## Troubleshooting

### Error: "Invalid private key format"

**Cause**: Private key not in correct PKCS#8 format or JSON escaping issue

**Fix**:
```bash
# Verify key format
openssl rsa -in sf_rsa_key.p8 -text -noout

# Re-convert if needed
openssl rsa -in old_key.pem -out new_key.pem
openssl pkcs8 -topk8 -inform PEM -in new_key.pem -out sf_rsa_key.p8 -nocrypt

# Verify JSON escaping (newlines should be \n)
cat sf_test.json | jq '.data.sf_private_key'
```

### Error: "JWT token is invalid"

**Cause**: Public key not assigned to user or mismatch

**Fix**:
```sql
-- In Snowflake, verify public key
DESC USER NOETL;

-- Re-assign if needed (remove header/footer, join lines)
ALTER USER NOETL SET RSA_PUBLIC_KEY='...';
```

### Error: "Failed to connect to Snowflake"

**Cause**: Network issue or incorrect account identifier

**Fix**:
```bash
# Verify account format (should be ACCOUNT-REGION)
# Example: NDCFGPC-MI21697 (not full URL)

# Test network connectivity
curl https://NDCFGPC-MI21697.snowflakecomputing.com

# Check worker logs for detailed error
kubectl logs -f deployment/noetl-worker -n noetl --tail=100
```

### Error: "Token resolution failed"

**Cause**: google-auth library not installed or credential type mismatch

**Fix**:
```bash
# Reinstall dependencies
pip install -e .

# Verify cryptography and google-auth
pip show cryptography google-auth

# Check credential type in database
curl -sS http://localhost:8082/api/credentials/google_sa_test | jq '.type'
# Should be: "google_service_account" or "gcp"
```

## Success Criteria

✅ **Snowflake Key-Pair Auth**:
- Playbook execution completes without MFA error
- Log shows "Using key-pair authentication"
- Data successfully transferred between Snowflake and PostgreSQL
- 5 rows inserted in `test_data_transfer` table

✅ **Google OAuth Token**:
- Token function resolves without errors
- HTTP request includes valid Bearer token
- Token is cached (subsequent calls use cache)
- Log shows token expiration tracking

## Quick Test Commands

```bash
# Full test suite (after setup)
cd /Users/kadyapam/projects/noetl/noetl

# 1. Register credentials with key-pair auth
curl -X POST http://localhost:8082/api/credentials \
  -H 'Content-Type: application/json' \
  --data-binary @tests/fixtures/credentials/sf_test.json

# 2. Execute Snowflake test playbook
.venv/bin/noetl execute playbook "tests/fixtures/playbooks/data_transfer/snowflake_postgres" \
  --host localhost --port 8082 --json | jq -r '.execution_id' > /tmp/exec_id.txt

# 3. Monitor until complete
watch -n 2 "curl -sS http://localhost:8082/api/execution/\$(cat /tmp/exec_id.txt) | jq '.status'"

# 4. Check results
curl -sS http://localhost:8082/api/execution/$(cat /tmp/exec_id.txt) | jq .
```

## Next Steps After Successful Test

1. **Update Documentation**: Add token examples to playbook guides
2. **Create Integration Tests**: Automate token auth testing in CI/CD
3. **Performance Testing**: Verify token caching reduces API calls
4. **Security Audit**: Review credential storage and token handling
5. **Migrate Production**: Update production playbooks to use key-pair auth
