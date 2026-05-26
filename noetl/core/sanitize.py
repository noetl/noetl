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
from typing import Any, Dict, Iterable, List, Optional, Set, Union

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

# Additional response-boundary patterns. These are intentionally more specific
# than the logging sanitizer's generic "long alphanumeric string" rule so
# execution ids, provider ids, and document ids remain visible in API responses.
SECRET_VALUE_PATTERNS: List[re.Pattern] = [
    re.compile(r"^Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"^Basic\s+[A-Za-z0-9+/=]+", re.IGNORECASE),
    re.compile(r"^eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+$"),
    re.compile(r"(?:^|[\"':\s])sk-[A-Za-z0-9][A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?:^|[\"':\s])sk-ant-[A-Za-z0-9][A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?:^|[\"':\s])AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"(?:^|[\"':\s])ya29\.[0-9A-Za-z_\-]+"),
    re.compile(r"(?:^|[\"':\s])gh[pousr]_[0-9A-Za-z_]{20,}"),
    re.compile(r"(?:^|[\"':\s])github_pat_[0-9A-Za-z_]{20,}"),
    re.compile(r"(?:^|[\"':\s])xox[baprs]-[0-9A-Za-z\-]{20,}"),
    re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    re.compile(
        r"(?i)([?&](?:key|api[_-]?key|token|access[_-]?token|id[_-]?token|"
        r"refresh[_-]?token|client[_-]?secret|signature)=)[^&\s]+"
    ),
]

RESPONSE_SENSITIVE_KEYS: Set[str] = {
    "keychain",
    "api_secret",
    "api-secret",
    "apisecret",
    "auth0_token",
    "auth0-token",
    "auth0_id_token",
    "auth0-id-token",
    "auth0_refresh_token",
    "auth0-refresh-token",
    "idtoken",
    "oauth",
    "jwt",
}

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


def redact_keychain_values(
    data: Any,
    additional_keys: Optional[Set[str]] = None,
    secret_values: Optional[Iterable[str]] = None,
    redaction: str = REDACTED,
    max_depth: int = 20,
) -> Any:
    """
    Redact secret-bearing values from API response payloads.

    This is a serialization-boundary sanitizer. It returns a redacted copy of
    ``data`` and does not mutate the stored workflow state or event log.

    Detection combines:
    - key-based matching for fields such as token, secret, api_key, auth, and
      keychain-derived names;
    - value-shape matching for bearer headers, JWTs, common provider key
      prefixes, private keys, and URLs carrying secret query parameters;
    - optional exact or embedded matches for caller-provided secret values.
    """
    normalized_keys = {str(key).lower().replace("-", "_") for key in (additional_keys or set())}
    normalized_values = {
        str(value)
        for value in (secret_values or set())
        if isinstance(value, str) and value
    }
    return _redact_response_recursive(
        data,
        normalized_keys,
        normalized_values,
        redaction,
        max_depth,
        0,
    )


def _is_response_secret_value(value: str, secret_values: Set[str]) -> bool:
    if not isinstance(value, str) or not value:
        return False

    if value in secret_values:
        return True
    for secret in secret_values:
        if len(secret) >= 8 and secret in value:
            return True

    if redact_url_credentials(value) != value:
        return True

    for pattern in SECRET_VALUE_PATTERNS:
        if pattern.search(value):
            return True

    return False


def _is_response_sensitive_key(key: str) -> bool:
    if _is_sensitive_key(key):
        return True
    key_lower = key.lower().replace("-", "_")
    if key_lower in RESPONSE_SENSITIVE_KEYS:
        return True
    for sensitive in RESPONSE_SENSITIVE_KEYS:
        if sensitive.replace("-", "_") in key_lower:
            return True
    return False


def _redact_response_recursive(
    data: Any,
    additional_keys: Set[str],
    secret_values: Set[str],
    redaction: str,
    max_depth: int,
    current_depth: int,
) -> Any:
    if current_depth >= max_depth:
        return data

    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            key_text = str(key)
            key_normalized = key_text.lower().replace("-", "_")
            if _is_response_sensitive_key(key_text) or key_normalized in additional_keys:
                result[key] = redaction
            else:
                result[key] = _redact_response_recursive(
                    value,
                    additional_keys,
                    secret_values,
                    redaction,
                    max_depth,
                    current_depth + 1,
                )
        return result

    if isinstance(data, list):
        return [
            _redact_response_recursive(
                item,
                additional_keys,
                secret_values,
                redaction,
                max_depth,
                current_depth + 1,
            )
            for item in data
        ]

    if isinstance(data, tuple):
        return tuple(
            _redact_response_recursive(
                item,
                additional_keys,
                secret_values,
                redaction,
                max_depth,
                current_depth + 1,
            )
            for item in data
        )

    if isinstance(data, str) and _is_response_secret_value(data, secret_values):
        return redaction

    return data


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
            key_is_sensitive = (
                _is_sensitive_key(key)
                or (isinstance(key, str) and key.lower() in additional_keys)
            )
            if key_is_sensitive:
                # The sensitive-key check uses partial substring matches
                # (``db_credential`` matches ``credential``, ``oauth_token``
                # matches ``token``, etc.) so we cannot blindly redact every
                # value under a matching key — that pattern destroys
                # credential alias references which the NoETL keychain uses
                # to look up actual secrets at tool execution time.
                # Example failure: a postgres task with
                # ``auth: "{{ db_credential }}"`` and workload
                # ``db_credential: pg_auth`` gets rendered to
                # ``auth: "pg_auth"`` (the alias name).  Pre-fix, this
                # function rewrote that to ``auth: "[REDACTED]"``, the
                # worker tried to GET ``/api/credentials/[REDACTED]`` and
                # the lookup 404'd — silently breaking every playbook that
                # routes a credential by alias.
                #
                # Strategy:
                #   - String values: only redact when ``_is_sensitive_value``
                #     matches (Bearer tokens, JWTs, long random secrets,
                #     PEM headers, etc.).  Short identifier-shaped strings
                #     pass through — they're alias references, not secrets.
                #   - Nested dict / list values: preserve the prior broad
                #     redaction since key-only inspection cannot reach
                #     individual leaves; recursion would re-encounter the
                #     same sensitive-key trap.
                #   - Other scalars (int, bool, None): pass through.
                #
                # Resolved secret values still get redacted on the
                # producer side via ``producer_scrub_payload`` (which is
                # keychain-manifest-aware) before they reach this layer,
                # so this relaxation does not widen the leak surface for
                # any value that already passed through the producer
                # boundary.
                if isinstance(value, str):
                    if _is_sensitive_value(value):
                        result[key] = redaction
                    else:
                        result[key] = value
                elif isinstance(value, (dict, list)):
                    result[key] = redaction
                else:
                    result[key] = value
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


# Matches the userinfo portion of a URL: ``scheme://[user[:pass]@]host...``.
# Captures the scheme + ``://`` (group 1) and the host-and-rest (group 2);
# the ``[^/@:]+(?::[^/@]*)?@`` middle is the userinfo segment we strip.
_URL_CREDENTIALS_RE = re.compile(
    r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*://)"  # e.g. nats://, postgres://, https://
    r"(?:[^/@:\s]+(?::[^/@\s]*)?@)"             # userinfo segment to redact
    r"(?P<rest>[^\s]+)"                          # host + path + query + fragment
)


def redact_url_credentials(value: str, placeholder: str = REDACTED) -> str:
    """Replace the userinfo segment of any URL found in ``value`` with a placeholder.

    Use this before logging or writing connection strings (NATS, Postgres,
    HTTP basic-auth, etc.) so that ``user:password@host`` does not leak into
    logs or debug files.

    Examples::

        >>> redact_url_credentials("nats://noetl:noetl@nats:4222")
        'nats://[REDACTED]@nats:4222'
        >>> redact_url_credentials("connect to postgres://u:p@db/noetl now")
        'connect to postgres://[REDACTED]@db/noetl now'
        >>> redact_url_credentials("nats://nats:4222")  # no userinfo
        'nats://nats:4222'

    Non-string inputs are returned unchanged so callers can pass through
    arbitrary types without a TypeError.
    """
    if not isinstance(value, str):
        return value

    def _replace(match: "re.Match[str]") -> str:
        return f"{match.group('scheme')}{placeholder}@{match.group('rest')}"

    return _URL_CREDENTIALS_RE.sub(_replace, value)
