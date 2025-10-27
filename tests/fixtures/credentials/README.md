# Credential Management

This directory contains credential templates for NoETL testing and development.

## ⚠️ SECURITY NOTICE

**NEVER commit real credentials to git!** 

All credential files in this directory should contain only placeholder values.

## Setup for Local Development

### Quick Start

Run the setup script to create local credential files:

```bash
./setup_local_credentials.sh
```

This creates `*.local.json` files that are gitignored. Edit these with your real credentials:

```bash
# Edit with your actual Snowflake credentials
vim tests/fixtures/credentials/sf_test.local.json
```

### Manual Setup

1. Copy template files to `.local.json` versions:
   ```bash
   cp sf_test.json sf_test.local.json
   cp pg_local.json pg_local.local.json
   ```

2. Edit the `.local.json` files with your actual credentials

3. Use the `.local.json` files in your code/tests

## File Naming Convention

- `*.json` - Template files with placeholders (committed to git)
- `*.local.json` - Your actual credentials (gitignored, never committed)
- `*_local.json` - Alternative local credential format (also gitignored)

## Available Credential Templates

### sf_test.json
Snowflake connection template for testing data transfers.

**Placeholders:**
- `sf_account`: "your_account.region"
- `sf_user`: "your_username"
- `sf_password`: "your_password"
- `sf_warehouse`: "COMPUTE_WH"
- `sf_database`: "TEST_DB"
- `sf_schema`: "PUBLIC"
- `sf_role`: "SYSADMIN"

### pg_local.json
PostgreSQL connection template for local development.

**Placeholders:**
- `db_host`: "localhost"
- `db_port`: "54321"
- `db_user`: "demo"
- `db_password`: "demo"
- `db_name`: "demo_noetl"

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
