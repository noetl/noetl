# Security and Redaction

NoETL enforces a strict separation between configuration and secret material to ensure sensitive data is handled securely throughout the execution pipeline.

## Core Principles

### Step-Scoped Secrets
- Secret material is resolved just-in-time for step execution
- Credentials are injected at render/exec time only
- **Never persisted** into `result` payloads or execution logs
- Memory is cleared immediately after step completion

### Automatic Redaction
- Logs and event streams automatically redact secret values
- Connection strings containing passwords are redacted
- API tokens and keys are masked in HTTP request logs
- DSNs show only non-sensitive components (host, port, database name)

### Source of Truth
- Secrets live in credential stores or external secret managers
- Playbooks reference secrets by key/identifier only
- No embedded credentials in YAML files
- Clear separation between configuration and sensitive data

## Redaction Examples

### Database Connections
```
# What gets logged:
Connecting with dbname=mydb user=myuser host=db.example.com port=5432 (password redacted)

# What is NOT logged:
Connecting with dbname=mydb user=myuser host=db.example.com port=5432 password=supersecret123
```

### HTTP Requests
```
# What gets logged:
Making HTTP request to https://api.example.com/data with headers: User-Agent=NoETL/1.0.0, Authorization=[REDACTED]

# What is NOT logged:
Making HTTP request to https://api.example.com/data with headers: Authorization=Bearer sk-1234567890abcdef
```

### DuckDB Credentials
```
# What gets logged:
Creating GCS secret with scope gs://my-bucket (key_id and secret redacted)

# What is NOT logged:
Creating GCS secret with key_id=GOOG1A2B3C4D5E6F secret_key=abcdef123456789
```

## Contributor Guidelines

When contributing to NoETL, follow these security practices:

### Never Log Secret Values
```python
# ❌ Don't do this
logger.info(f"Using password: {password}")

# ✅ Do this instead
logger.info(f"Connecting to database {host}:{port}/{dbname} (credentials redacted)")
```

### Redact Connection Strings
```python
# ❌ Don't do this
logger.info(f"DSN: {dsn}")

# ✅ Do this instead
logger.info(f"Connecting to {parsed_dsn.host}:{parsed_dsn.port}/{parsed_dsn.database} (password redacted)")
```

### Safe Logging Patterns
```python
# Safe to log: non-sensitive identifiers
logger.info(f"Using credential key: {credential_key}")

# Safe to log: connection metadata
logger.info(f"Database: {db_name}, Host: {db_host}, Port: {db_port}")

# Safe to log: execution context
logger.info(f"Step: {step_name}, Execution: {execution_id}")
```

### Example: Redacted DSN Logging
```python
def create_connection(dsn: str) -> Connection:
    parsed = parse_dsn(dsn)
    logger.info(f"Connecting to {parsed.host}:{parsed.port}/{parsed.database} user={parsed.username} (password redacted)")
    return connect(dsn)
```

## Implementation Details

### Credential Resolution Flow
1. **Playbook Parse**: Only credential keys are extracted from YAML
2. **Worker Request**: Worker requests credentials from Server by key
3. **Server Lookup**: Server resolves credentials from store
4. **Ephemeral Injection**: Credentials injected into step context
5. **Plugin Execution**: Plugin uses credentials to establish connections
6. **Memory Cleanup**: Credential values cleared from memory
7. **Log Redaction**: Any logged output is automatically redacted

### Secret Manager Integration
- External secret managers (Vault, AWS SM, GCP SM) are queried at runtime
- `{{ secret.* }}` templates are resolved during step execution
- Values are never cached or persisted beyond single step scope
- Audit logs in secret managers track all access

## Security Validation

### Static Analysis
- Playbook validation ensures no embedded secrets in YAML
- CI/CD pipelines can scan for credential patterns
- Schema validation rejects `with:` clauses containing secret-like patterns

### Runtime Monitoring
- All credential access is logged (with redaction)
- Execution events track credential usage without exposing values
- Failed authentication attempts are logged safely

### Audit Trail
- Event logs record which credentials were used in which steps
- Timestamps and execution context preserved
- Secret values themselves never appear in audit logs

This security model ensures that NoETL can safely handle sensitive data in production environments while maintaining full auditability and compliance with security best practices.

