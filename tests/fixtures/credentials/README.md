# Test Credentials Guide

This directory contains example credential templates for testing NoETL's authentication systems.

## 🔐 Security Notice

**NEVER commit actual credentials to git!** All `.json` files (except `.example` files) are gitignored.

## Credential Types

### 1. Snowflake (RSA Key-Pair Authentication)

**File**: `sf_test.json` (based on `sf_test.json.example`)

**How to set up**:

1. **Generate RSA key pair** (macOS/Linux):
   ```bash
   # Generate private key (no passphrase)
   openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out sf_rsa_key.p8 -nocrypt
   
   # Generate public key
   openssl rsa -in sf_rsa_key.p8 -pubout -out sf_rsa_key.pub
   ```

2. **Extract public key without headers**:
   ```bash
   cat sf_rsa_key.pub | grep -v "BEGIN PUBLIC KEY" | grep -v "END PUBLIC KEY" | tr -d '\n'
   ```

3. **Assign public key to Snowflake user**:
   ```sql
   -- In Snowflake web UI or SnowSQL
   ALTER USER NOETL SET RSA_PUBLIC_KEY='<public_key_without_headers>';
   ```

4. **Format private key for JSON**:
   ```bash
   # Convert newlines to \n for JSON
   cat sf_rsa_key.p8 | awk 'NF {sub(/\r/, ""); printf "%s\\n",$0;}'
   ```

5. **Update `sf_test.json`**:
   - Copy `sf_test.json.example` to `sf_test.json`
   - Set `sf_private_key` to the formatted private key (with `\n` literals)
   - Keep the `-----BEGIN PRIVATE KEY-----` and `-----END PRIVATE KEY-----` headers
   - Set `sf_private_key_passphrase` to empty string `""` if no passphrase

**Reference**: `docs/snowflake_keypair_auth.md`

---

### 2. Google OAuth (Service Account)

**File**: `google_oauth.json` (based on `google_oauth.json.example`)

**Option A: Use Your Existing gcloud Credentials** (Recommended for local testing)

If you already have gcloud configured:

```bash
# Run the copy script
./tests/fixtures/credentials/copy_gcloud_credentials.sh

# This creates google_oauth.json using your existing OAuth credentials
# from ~/.config/gcloud/legacy_credentials/your-email@gmail.com/adc.json
```

**Option B: Download Service Account Key** (For production use)

**How to set up**:

1. **Download service account key from GCP**:
   - Go to [GCP Console](https://console.cloud.google.com) → IAM & Admin → Service Accounts
   - Select your service account (or create a new one)
   - Keys tab → Add Key → Create new key → JSON
   - Download the JSON file

2. **Required permissions**:
   - For Secret Manager: `roles/secretmanager.secretAccessor`
   - For GCS: `roles/storage.objectViewer` or higher
   - For general use: `roles/iam.serviceAccountTokenCreator` (if using impersonation)

3. **Copy the downloaded JSON**:
   ```bash
   cp ~/Downloads/your-project-id-xxxxx.json tests/fixtures/credentials/google_oauth.json
   ```

4. **Verify JSON structure** has these fields:
   - `type`: "service_account"
   - `project_id`: Your GCP project ID
   - `private_key`: RSA private key (with `\n` as literal string)
   - `client_email`: Service account email
   - `client_id`: Client ID

5. **Register credential**:
   ```bash
   curl -X POST http://localhost:8083/api/credentials \
     -H 'Content-Type: application/json' \
     --data-binary @tests/fixtures/credentials/google_oauth.json
   ```

---

### 3. Google OAuth (Impersonation)

**File**: `google_oauth_impersonate.json` (based on `google_oauth_impersonate.json.example`)

**When to use**: When you need to impersonate another service account for elevated permissions.

**How to set up**:

1. **Create source service account** (the one doing impersonation):
   - Download its JSON key as described above

2. **Grant impersonation permission**:
   ```bash
   gcloud iam service-accounts add-iam-policy-binding \
     target-sa@your-project-id.iam.gserviceaccount.com \
     --member="serviceAccount:source-sa@your-project-id.iam.gserviceaccount.com" \
     --role="roles/iam.serviceAccountTokenCreator"
   ```

3. **Update `google_oauth_impersonate.json`**:
   - Set `impersonate_service_account` to target service account email
   - Set `source_credentials` to the source service account JSON key

**Use case**: CI/CD pipelines, cross-project access, temporary elevated permissions

---

### 4. PostgreSQL

**File**: `pg_local.json`

Standard username/password authentication for local PostgreSQL:

```json
{
  "name": "pg_local",
  "type": "postgres",
  "data": {
    "db_host": "localhost",
    "db_port": "54321",
    "db_user": "demo",
    "db_password": "demo",
    "db_name": "demo_noetl"
  }
}
```

---

### 5. NATS JetStream

**File**: `nats_credential.json` (based on `nats_credential.json.template`)

NATS credential for K/V Store, Object Store, and JetStream messaging. Used by Auth0 playbooks for gateway session management.

```json
{
  "name": "nats_credential",
  "type": "nats",
  "description": "NATS JetStream credential for K/V Store session management",
  "tags": ["nats", "jetstream", "kv", "sessions", "auth0"],
  "data": {
    "nats_url": "nats://nats.nats.svc.cluster.local:4222",
    "nats_user": "noetl",
    "nats_password": "noetl"
  }
}
```

**Connection Parameters**:

| Parameter | Description |
|-----------|-------------|
| `nats_url` | NATS server URL (e.g., `nats://localhost:4222`) |
| `nats_user` | NATS username (optional if no auth) |
| `nats_password` | NATS password (optional if no auth) |
| `nats_token` | Alternative: token-based auth |
| `tls_cert` | TLS client certificate path (optional) |
| `tls_key` | TLS client key path (optional) |
| `tls_ca` | TLS CA certificate path (optional) |

**Usage in Playbooks**:

```yaml
- step: store_session
  tool:
    kind: nats
    auth: nats_credential
    operation: kv_put
    bucket: sessions
    key: "{{ session_id }}"
    value:
      user_id: "{{ user_id }}"
      expires_at: "{{ expires_at }}"
```

**Supported Operations**:
- K/V Store: `kv_get`, `kv_put`, `kv_delete`, `kv_keys`, `kv_purge`
- Object Store: `object_get`, `object_put`, `object_delete`, `object_list`, `object_info`
- JetStream: `js_publish`, `js_get_msg`, `js_stream_info`

**Kind Cluster Setup**:

NATS is deployed in the `nats` namespace with NodePort access:
- Internal: `nats://nats.nats.svc.cluster.local:4222`
- External (NodePort): `nats://localhost:30422`
- Monitoring: `http://localhost:30822`

**Register credential**:
```bash
curl -X POST http://localhost:8083/api/credentials \
  -H 'Content-Type: application/json' \
  --data-binary @tests/fixtures/credentials/nats_credential.json
```

---

### 6. Interactive Brokers OAuth

**File**: `ib_oauth.json.example`

Interactive Brokers supports OAuth 2.0 for server-to-server API authentication:

```json
{
  "name": "ib_oauth",
  "type": "interactive_brokers_oauth",
  "description": "Interactive Brokers OAuth credentials",
  "tags": ["oauth", "ib", "trading"],
  "data": {
    "consumer_key": "your-consumer-key",
    "consumer_secret": "your-consumer-secret",
    "account_id": "DU8027814",
    "environment": "paper",
    "api_base_url": "https://api.ibkr.com/v1/api",
    "oauth_version": "2.0"
  }
}
```

**Setup Steps**:
1. Login to IBKR Client Portal (paper trading: https://ndcdyn.interactivebrokers.com)
2. Navigate to Settings → API → OAuth Applications
3. Create new OAuth application
4. Copy Consumer Key and Consumer Secret
5. Use paper trading account for testing (expires after 60 days inactivity)

**Paper Trading Account**:
- Username: `wzeeym257`
- Password: `Test202$`
- Account ID: `DU8027814`

**Important**: Username/password are only used to login to IBKR portal to create OAuth app. The OAuth credentials (consumer_key/secret) are what gets stored and used for API access.

### pg_local.json
PostgreSQL connection template for local development.

**Placeholders:**
- `db_host`: "localhost"
- `db_port`: "54321"
- `db_user`: "demo"
- `db_password`: "demo"
- `db_name`: "demo_noetl"

---

### 7. Interactive Brokers OAuth 2.0 (JWT-Based Client Assertion)

**File**: `ib_oauth.json` (based on `ib_oauth.json.example`)

**How to set up**:

IBKR uses JWT-based client assertion (RFC 7521) instead of simple consumer_key/secret OAuth. This requires signing tokens with an RSA private key.

1. **Create OAuth Application in IBKR Portal**:
   - Login to [Client Portal](https://www.interactivebrokers.com)
   - Navigate to Settings → API → OAuth Applications
   - Create new OAuth application
   - Generate RSA key pair (2048-bit or higher)
   - Upload public key to IBKR
   - Note the `client_id` and `key_id` assigned by IBKR

2. **Save Private Key**:
   ```bash
   # IBKR provides private key in PEM format
   # Save it to a temporary file for reference
   cat > ib_private_key.pem <<'EOF'
   -----BEGIN PRIVATE KEY-----
   [Your private key here]
   -----END PRIVATE KEY-----
   EOF
   ```

3. **Format Private Key for JSON**:
   ```bash
   # Convert newlines to \n for JSON (keep headers)
   cat ib_private_key.pem | awk 'NF {sub(/\r/, ""); printf "%s\\n",$0;}'
   ```

4. **Update `ib_oauth.json`**:
   ```json
   {
     "name": "ib_oauth",
     "type": "ib_oauth",
     "data": {
       "client_id": "your-oauth-client-id",
       "key_id": "your-rsa-key-id",
       "private_key": "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----",
       "api_base_url": "https://api.ibkr.com/v1"
     }
   }
   ```

5. **Test Authentication**:
   ```bash
   # Register credential
   curl -X POST http://localhost:8083/api/credentials \
     -H 'Content-Type: application/json' \
     --data-binary @tests/fixtures/credentials/ib_oauth.json
   
   # Execute OAuth test playbook
   .venv/bin/noetl execute playbook "tests/fixtures/playbooks/oauth/interactive_brokers" \
     --host localhost --port 8083
   ```

**Important Notes**:
- JWT tokens are signed using RS256 algorithm
- Client assertion JWT includes: iss, sub, aud, exp, iat claims
- Access tokens are valid for ~24 hours (86399 seconds)
- Tokens are cached and auto-refreshed before expiry
- Paper trading account: Username `wzeeym257`, Account `DU8027814`

**Token Provider Implementation**: `noetl/core/auth/ib_provider.py`

**Reference**: 
- `tests/fixtures/playbooks/oauth/interactive_brokers/OAUTH_IMPLEMENTATION.md`
- `tests/fixtures/playbooks/oauth/interactive_brokers/README.md`
- IBKR OAuth API: `tests/fixtures/playbooks/oauth/interactive_brokers/api-docs.json`

---

### gcs_hmac_local.json
Google Cloud Storage HMAC credentials template.

**Note:** This file is always gitignored.

## If Credentials Were Accidentally Committed

If you accidentally committed real credentials:

1. **Immediately run the cleanup script:**
   ```bash
   ./clean_credentials_history.sh
   ```

2. **Force push the cleaned history:**
   ```bash
   git push origin master --force
   ```

3. **Rotate the compromised credentials immediately**

4. **Notify team members** to re-clone or reset their branches

## Best Practices

1. ✅ Always use `.local.json` files for actual credentials
2. ✅ Keep template files with obvious placeholder values
3. ✅ Review commits before pushing to ensure no credentials leaked
4. ✅ Use environment variables for production credentials
5. ✅ Store production credentials in secret management systems (e.g., AWS Secrets Manager, HashiCorp Vault)

6. ❌ Never commit files containing real passwords, API keys, or tokens
7. ❌ Never share credential files via chat, email, or other insecure channels
8. ❌ Never hardcode credentials in code

## Production Credentials

For production deployments, use:

- **Kubernetes Secrets** for K8s deployments
- **Environment Variables** for containerized apps  
- **Secret Management Services** (AWS Secrets Manager, Google Secret Manager, etc.)
- **NoETL's built-in secret management** via the credentials API

Never use file-based credentials in production!

---

## Testing Token-Based Authentication

After registering credentials, test token generation:

```bash
# Start NoETL locally
noetl server start

# Register credentials
curl -X POST http://localhost:8083/api/credentials \
  -H 'Content-Type: application/json' \
  --data-binary @tests/fixtures/credentials/google_oauth.json

# Execute test playbook
.venv/bin/noetl execute playbook "tests/fixtures/playbooks/oauth/google_secret_manager" \
  --host localhost --port 8083
```

---

## Credential Storage

All credentials are stored encrypted in the `noetl.credential` table using `pycryptodome` AES encryption. The encryption key is derived from the `NOETL_SECRET_KEY` environment variable.

---

## Getting Help

- **Snowflake**: See `docs/snowflake_keypair_auth.md`
- **Token Auth**: See `docs/token_auth_implementation.md`
- **Testing**: See `docs/testing_token_auth.md`
- **Google Service Accounts**: See `docs/google_cloud_service_account.md`

---

## Quick Setup Scripts

### copy_gcloud_credentials.sh

Automatically copies your existing gcloud OAuth credentials to NoETL format:

```bash
./tests/fixtures/credentials/copy_gcloud_credentials.sh
```

**What it does**:
1. Reads your gcloud OAuth credentials from `~/.config/gcloud/legacy_credentials/`
2. Wraps them in NoETL credential format
3. Saves to `tests/fixtures/credentials/google_oauth.json`
4. Shows next steps for registration

**When to use**:
- ✅ Local development and testing
- ✅ You already have gcloud configured
- ✅ Quick prototyping

**When NOT to use**:
- ❌ Production deployments (use service accounts instead)
- ❌ CI/CD pipelines (use service accounts)
- ❌ Shared environments (credentials are tied to your personal Google account)

---
