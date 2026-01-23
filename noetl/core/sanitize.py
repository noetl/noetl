"""
Sensitive data sanitization for NoETL.

This module provides utilities to redact sensitive information like bearer tokens,
passwords, API keys, and other credentials from dictionaries before they are
logged or stored in events.

Usage:
    from noetl.core.sanitize import sanitize_sensitive_data

    # Sanitize a dictionary before logging/storing
    safe_data = sanitize_sensitive_data(data)
"""

import re
from typing import Any, Dict, List, Optional, Set, Union

# Keys that indicate sensitive data (case-insensitive matching)
SENSITIVE_KEYS: Set[str] = {
    # Authentication
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "bearer",
    "api_key",
    "apikey",
    "api-key",
    "access_token",
    "access-token",
    "refresh_token",
    "refresh-token",
    "auth_token",
    "auth-token",
    "authorization",
    "auth",
    "credential",
    "credentials",
    "private_key",
    "private-key",
    "privatekey",
    "secret_key",
    "secret-key",
    "secretkey",
    "client_secret",
    "client-secret",
    "clientsecret",
    # Database
    "connection_string",
    "connection-string",
    "connectionstring",
    "db_password",
    "db-password",
    "database_password",
    # Cloud
    "aws_secret",
    "aws-secret",
    "gcp_key",
    "gcp-key",
    "azure_key",
    "azure-key",
    # SSH/TLS
    "ssh_key",
    "ssh-key",
    "sshkey",
    "passphrase",
    "pem",
    "cert",
    "certificate",
    # OAuth
    "oauth_token",
    "oauth-token",
    "id_token",
    "id-token",
    # Encryption
    "encryption_key",
    "encryption-key",
    "decrypt_key",
    "decrypt-key",
    "master_key",
    "master-key",
    # Snowflake specific
    "snowflake_password",
    "snowflake_token",
    "private_key_passphrase",
}

# Patterns for detecting sensitive values (regardless of key name)
SENSITIVE_PATTERNS: List[re.Pattern] = [
    # Bearer tokens
    re.compile(r"^Bearer\s+[A-Za-z0-9\-_\.]+", re.IGNORECASE),
    # Basic auth header
    re.compile(r"^Basic\s+[A-Za-z0-9+/=]+", re.IGNORECASE),
    # JWT tokens (header.payload.signature format)
    re.compile(r"^eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+$"),
    # API keys (common formats: long alphanumeric strings)
    re.compile(r"^[A-Za-z0-9]{32,}$"),
    # AWS secret keys
    re.compile(r"^[A-Za-z0-9/+=]{40}$"),
    # Private key content
    re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
]

# Default redaction placeholder
REDACTED = "[REDACTED]"


def _is_sensitive_key(key: str) -> bool:
    """
    Check if a key indicates sensitive data.

    Args:
        key: Dictionary key to check

    Returns:
        True if the key indicates sensitive data
    """
    if not isinstance(key, str):
        return False
    key_lower = key.lower().replace("-", "_")

    # Direct match
    if key_lower in SENSITIVE_KEYS:
        return True

    # Partial match (key contains sensitive term)
    for sensitive in SENSITIVE_KEYS:
        if sensitive in key_lower:
            return True

    return False


def _is_sensitive_value(value: str) -> bool:
    """
    Check if a value looks like sensitive data.

    Args:
        value: String value to check

    Returns:
        True if the value looks like sensitive data
    """
    if not isinstance(value, str):
        return False

    for pattern in SENSITIVE_PATTERNS:
        if pattern.search(value):
            return True

    return False


def sanitize_sensitive_data(
    data: Any,
    additional_keys: Optional[Set[str]] = None,
    redaction: str = REDACTED,
    max_depth: int = 20
) -> Any:
    """
    Recursively sanitize sensitive data from a dictionary or list.

    This function:
    - Redacts values for keys that match sensitive patterns (password, token, etc.)
    - Redacts string values that match sensitive value patterns (Bearer tokens, JWTs)
    - Recursively processes nested dictionaries and lists
    - Returns a new object (does not modify the original)

    Args:
        data: Data to sanitize (dict, list, or scalar)
        additional_keys: Additional key names to treat as sensitive
        redaction: Replacement string for redacted values
        max_depth: Maximum recursion depth to prevent stack overflow

    Returns:
        Sanitized copy of the data

    Example:
        >>> data = {"user": "admin", "password": "secret123", "Authorization": "Bearer xyz"}
        >>> sanitize_sensitive_data(data)
        {"user": "admin", "password": "[REDACTED]", "Authorization": "[REDACTED]"}
    """
    return _sanitize_recursive(data, additional_keys or set(), redaction, max_depth, 0)


def _sanitize_recursive(
    data: Any,
    additional_keys: Set[str],
    redaction: str,
    max_depth: int,
    current_depth: int
) -> Any:
    """Internal recursive sanitization helper."""

    # Prevent infinite recursion
    if current_depth >= max_depth:
        return data

    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            # Check if key indicates sensitive data
            if _is_sensitive_key(key) or (isinstance(key, str) and key.lower() in additional_keys):
                result[key] = redaction
            else:
                result[key] = _sanitize_recursive(
                    value, additional_keys, redaction, max_depth, current_depth + 1
                )
        return result

    elif isinstance(data, list):
        return [
            _sanitize_recursive(item, additional_keys, redaction, max_depth, current_depth + 1)
            for item in data
        ]

    elif isinstance(data, str):
        # Check if string value looks like sensitive data
        if _is_sensitive_value(data):
            return redaction
        return data

    else:
        # Scalars (int, float, bool, None, etc.) - return as-is
        return data


def sanitize_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """
    Sanitize HTTP headers for logging.

    Specifically redacts Authorization, Cookie, and other sensitive headers.

    Args:
        headers: HTTP headers dictionary

    Returns:
        Sanitized headers dictionary
    """
    sensitive_header_names = {
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
        "x-access-token",
        "proxy-authorization",
        "www-authenticate",
    }

    result = {}
    for key, value in (headers or {}).items():
        if key.lower() in sensitive_header_names or _is_sensitive_key(key):
            result[key] = REDACTED
        else:
            result[key] = value
    return result


def sanitize_for_logging(data: Any, max_length: int = 1000) -> str:
    """
    Sanitize data and convert to string for logging.

    Args:
        data: Data to sanitize and stringify
        max_length: Maximum length of returned string

    Returns:
        Sanitized string representation, truncated if necessary
    """
    import json

    sanitized = sanitize_sensitive_data(data)

    try:
        result = json.dumps(sanitized, default=str)
    except (TypeError, ValueError):
        result = str(sanitized)

    if len(result) > max_length:
        return result[:max_length - 3] + "..."

    return result


def mask_value(value: str, visible_start: int = 4, visible_end: int = 4) -> str:
    """
    Partially mask a sensitive value, showing only start and end characters.

    Useful for logging previews of tokens/keys without revealing full value.

    Args:
        value: Value to mask
        visible_start: Number of characters to show at start
        visible_end: Number of characters to show at end

    Returns:
        Masked value (e.g., "Bear...xyz" or "[REDACTED]" if too short)
    """
    if not isinstance(value, str):
        return REDACTED

    if len(value) <= visible_start + visible_end + 3:
        return REDACTED

    return f"{value[:visible_start]}...{value[-visible_end:]}"
