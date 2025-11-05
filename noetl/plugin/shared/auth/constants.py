"""
Authentication constants and field definitions.
"""

# Supported authentication types
AUTH_TYPES = {
    "postgres",
    "hmac", 
    "s3",
    "bearer",
    "basic", 
    "header",
    "api_key"
}

# Supported providers
AUTH_PROVIDERS = {
    "credential_store",  # Default: NoETL credential store
    "secret_manager",    # External secret manager
    "inline"            # Inline in playbook (not recommended for secrets)
}

# Fields that should be redacted in logs
REDACTED_FIELDS = {
    "db_password", "password", "secret_key", "token", "value", 
    "access_token", "refresh_token", "client_secret"
}
