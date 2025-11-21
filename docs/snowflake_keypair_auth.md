# Snowflake Key-Pair Authentication Setup

This guide explains how to set up RSA key-pair authentication for Snowflake to bypass MFA/TOTP requirements.

## Prerequisites

- Snowflake account with ACCOUNTADMIN or SECURITYADMIN role
- OpenSSL or similar tool for generating RSA keys
- NoETL with token authentication support

## Step 1: Generate RSA Key Pair

Generate a 2048-bit RSA private key:

```bash
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt
```

Or with passphrase protection:

```bash
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8
```

Extract the public key:

```bash
openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub
```

## Step 2: Assign Public Key to Snowflake User

Connect to Snowflake and run:

```sql
-- Remove the header/footer and newlines from the public key
ALTER USER NOETL SET RSA_PUBLIC_KEY='MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...';

-- Verify the key was set
DESC USER NOETL;
```

## Step 3: Create NoETL Credential

Create a JSON credential file with the private key:

```json
{
  "name": "sf_test_keypair",
  "type": "snowflake",
  "description": "Snowflake key-pair authentication",
  "tags": ["test", "snowflake", "keypair"],
  "data": {
    "sf_account": "NDCFGPC-MI21697",
    "sf_user": "NOETL",
    "sf_private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC...\n-----END PRIVATE KEY-----",
    "sf_private_key_passphrase": "",
    "sf_warehouse": "SNOWFLAKE_LEARNING_WH",
    "sf_database": "TEST_DB",
    "sf_schema": "PUBLIC",
    "sf_role": "ACCOUNTADMIN"
  }
}
```

**Important Notes:**
- Include the full private key with `-----BEGIN/END PRIVATE KEY-----` headers
- Preserve `\n` for line breaks in the JSON string
- Use `sf_private_key_passphrase` if the key is encrypted
- Remove `sf_password` field (not used with key-pair auth)

## Step 4: Register Credential

```bash
# Using curl
curl -X POST http://localhost:8000/api/credential \
  -H "Content-Type: application/json" \
  -d @sf_test_keypair.json

# Using NoETL CLI (if available)
noetl credential create --file sf_test_keypair.json
```

## Step 5: Update Playbook

Update your playbook to use the new credential:

```yaml
workload:
  sf_auth: sf_test_keypair  # Use key-pair credential
  pg_auth: pg_local

workflow:
  - step: query_snowflake
    tool: snowflake
    auth: "{{ workload.sf_auth }}"
    command: |
      SELECT CURRENT_USER(), CURRENT_ROLE();
```

## Testing

Verify the connection works:

```bash
task test-snowflake-postgres-full
```

## Troubleshooting

### "Invalid private key format" Error

- Check that the private key includes the full PEM headers
- Verify the key is in PKCS#8 format (not PKCS#1)
- Check for proper escaping of newlines in JSON (`\n`)

### "JWT token is invalid" Error

- Verify the public key was correctly assigned to the Snowflake user
- Check that the user account and key match
- Ensure the private key hasn't been corrupted

### "Failed to connect" Error

- Verify the account identifier is correct
- Check network connectivity to Snowflake
- Verify the warehouse, database, and role exist

## Security Best Practices

1. **Never commit private keys to version control**
2. **Use encrypted private keys with passphrases**
3. **Rotate keys regularly (every 90 days)**
4. **Store keys in secure credential management systems**
5. **Limit key-pair auth to service accounts only**

## References

- [Snowflake Key-Pair Authentication Documentation](https://docs.snowflake.com/en/user-guide/key-pair-auth)
- [OpenSSL Command Guide](https://www.openssl.org/docs/)
