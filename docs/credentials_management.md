# NoETL Credentials Management

Complete credential management system with UI, API, and CLI support for secure storage and retrieval of authentication data.

## Features

### UI Dashboard (`/credentials`)
- **View Credentials**: Browse all stored credentials with search and filtering
- **Create/Upload**: Three input modes:
  - **Form**: Guided form with type-specific templates
  - **JSON**: Paste complete credential JSON
  - **File Upload**: Upload credential JSON files
- **Edit**: Modify existing credentials
- **Delete**: Remove credentials with confirmation
- **View Data**: Toggle to show/hide decrypted credential data
- **Search**: Real-time search by name, type, description, or tags
- **Type Color Coding**: Visual distinction for different credential types

### Supported Credential Types
- `postgres`: PostgreSQL database
- `snowflake`: Snowflake data warehouse (password or RSA key-pair)
- `google_service_account`: GCP service account
- `google_oauth`: Google OAuth
- `httpBearerAuth`: HTTP Bearer token
- `http`: HTTP authentication
- `generic`: Generic credentials

## Snowflake RSA Key-Pair Authentication

### Why Key-Pair Authentication?
Snowflake key-pair authentication bypasses MFA/TOTP requirements, enabling automated workflows without manual token entry.

### Generate Key Pair
```bash
cd tests/fixtures/credentials
./generate_snowflake_keypair.sh
```

This generates:
- `sf_rsa_key.p8`: Private key (keep secure, added to .gitignore)
- `sf_rsa_key.pub`: Public key (to assign in Snowflake)
- `sf_test_keypair_example.json`: Example credential JSON

### Assign Public Key in Snowflake
```sql
-- Remove header/footer from public key and join lines
ALTER USER NOETL SET RSA_PUBLIC_KEY='MIIBIjANBg...';

-- Verify
DESC USER NOETL;
```

### Credential Format
```json
{
  "name": "sf_test",
  "type": "snowflake",
  "description": "Snowflake with RSA key-pair auth",
  "tags": ["snowflake", "keypair"],
  "data": {
    "sf_account": "ACCOUNT-LOCATOR",
    "sf_user": "USERNAME",
    "sf_private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----",
    "sf_warehouse": "WAREHOUSE_NAME",
    "sf_database": "DATABASE_NAME",
    "sf_schema": "PUBLIC",
    "sf_role": "ROLE_NAME"
  }
}
```

## API Usage

### Create/Update Credential
```bash
curl -X POST http://localhost:8082/api/credentials \
  -H 'Content-Type: application/json' \
  --data-binary @credential.json
```

### List Credentials
```bash
# All credentials
curl http://localhost:8082/api/credentials

# Filter by type
curl http://localhost:8082/api/credentials?type=snowflake

# Search
curl http://localhost:8082/api/credentials?q=production
```

### Get Credential
```bash
# Without data
curl http://localhost:8082/api/credentials/sf_test

# With decrypted data
curl http://localhost:8082/api/credentials/sf_test?include_data=true
```

### Delete Credential
```bash
curl -X DELETE http://localhost:8082/api/credentials/sf_test
```

## CLI Usage

### Register Test Credentials
```bash
task test:k8s:register-credentials
# or
task rtc
```

This registers:
- `pg_k8s`: Kubernetes PostgreSQL
- `pg_local`: Local PostgreSQL
- `gcs_hmac_local`: GCS HMAC credentials
- `sf_test`: Snowflake test credentials
- `google_oauth`: Google OAuth

### Execute Playbook with Credentials
```bash
.venv/bin/noetl execute playbook "path/to/playbook" \
  --host localhost --port 8082 \
  --payload '{"pg_auth": "pg_local"}' --merge --json
```

## Test Credential Files

All test credentials are in `tests/fixtures/credentials/`:

- `pg_k8s.json`: Kubernetes PostgreSQL
- `pg_local.json`: Local PostgreSQL development
- `sf_test.json.template`: Snowflake password auth (template)
- `sf_test_keypair.json.example`: Snowflake RSA key-pair (example)
- `gcs_hmac_local.json.template`: GCS HMAC credentials
- `google_oauth.json.example`: Google OAuth
- `matrixcare_snowflake_prod.json`: Production Snowflake

## Credential Storage

### Database Schema
```sql
CREATE TABLE credential (
  id SERIAL PRIMARY KEY,
  name VARCHAR(255) UNIQUE NOT NULL,
  type VARCHAR(100) NOT NULL,
  data_encrypted BYTEA NOT NULL,          -- AES-256 encrypted
  meta JSONB,
  tags TEXT[],
  description TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Encryption
- **Algorithm**: AES-256-GCM
- **Key Source**: `NOETL_SECRET_KEY` environment variable
- **At Rest**: All credential data encrypted in database
- **In Transit**: HTTPS for API calls (production)
- **Decryption**: On-demand when `include_data=true`

## Security Best Practices

1. **Private Keys**: Never commit private keys to version control
2. **Key Rotation**: Rotate Snowflake RSA keys periodically
3. **Access Control**: Limit credential access to authorized users
4. **Audit Logs**: Monitor credential usage (coming soon)
5. **Secret Management**: Use environment variables for sensitive keys
6. **Network Security**: Use HTTPS in production
7. **Principle of Least Privilege**: Grant minimal required permissions

## Testing

### Test Snowflake Connection
```bash
# After registering sf_test credential
.venv/bin/noetl execute playbook \
  "tests/fixtures/playbooks/data_transfer/snowflake_postgres" \
  --host localhost --port 8082 --json
```

**Expected Success Indicators**:
- Logs show: "Using key-pair authentication for Snowflake account"
- Logs show: "Successfully connected to Snowflake"
- No MFA/TOTP error
- Execution status: "success"
- Data transferred successfully

### Complete Test Environment Setup
```bash
task test:k8s:setup-environment
# or
task ste
```

This runs:
1. Register all test credentials
2. Register all test playbooks
3. Verify cluster health

## Troubleshooting

### "Method Not Allowed (405)" on DELETE
**Problem**: DELETE endpoint returns 405 error  
**Solution**: Restart the NoETL server to register the new DELETE endpoint
```bash
# For local development
task noetl:local-server-stop
task noetl:local-server-debug

# For Kubernetes
kubectl rollout restart deployment/noetl-server -n noetl
kubectl rollout restart deployment/noetl-worker -n noetl
```

### "Credential not found"
- Check credential name spelling
- List all credentials: `curl http://localhost:8082/api/credentials`

### "Invalid JSON format"
- Validate JSON: `cat credential.json | jq .`
- Check for trailing commas, quotes

### Snowflake MFA Error
- Verify RSA public key assigned: `DESC USER username;`
- Check private key format (PEM with headers/footers)
- Ensure `sf_private_key` field has proper newlines: `\n`

### Decryption Failed
- Verify `NOETL_SECRET_KEY` matches between create and retrieve
- Check key length (must be 32 bytes base64-encoded)

## Documentation

- **API Reference**: `docs/api_usage.md`
- **Token Auth**: `docs/token_auth_implementation.md`
- **Snowflake Setup**: `docs/snowflake_keypair_auth.md`
- **Testing Guide**: `docs/testing_token_auth.md`

## UI Screenshots

### Credentials List
![Credentials List](docs/images/credentials-list.png)

### Create Credential (Form Mode)
![Create Form](docs/images/credentials-create-form.png)

### Upload Credential (File Mode)
![Upload File](docs/images/credentials-upload.png)

### View Credential Data
![View Data](docs/images/credentials-view-data.png)

---

**Version**: 1.0.0  
**Last Updated**: December 3, 2025  
**Branch**: AHM-3723
