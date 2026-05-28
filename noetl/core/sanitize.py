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


def _looks_like_template_or_code(value: str) -> bool:
    """Best-effort detection of strings that are templates or source code
    rather than resolved leaf values.

    The value-shape secret patterns in ``SECRET_VALUE_PATTERNS`` (e.g.
    ``[?&]key=<value>`` URL credentials) match templated URLs that contain
    f-string / Jinja substitution markers — e.g. the google-places MCP's
    ``f"...?key={urllib.parse.quote(key, safe='')}"`` line.  When the
    value matched after ``key=`` is itself a substitution marker, the
    string is metadata describing how to build a URL at runtime, not a
    resolved URL carrying an actual key.

    Treating such strings as secrets and replacing them with the
    redaction sentinel destroys the python tool's ``code`` block when
    the playbook contains URL-building patterns.  Concrete failure on
    noetl-demo-19700101 GKE: the google-places MCP dispatch returned
    ``NameError: name 'REDACTED' is not defined`` because the entire
    code string was replaced by ``"[REDACTED]"`` and exec(code)
    evaluated ``[REDACTED]`` as a list-literal containing a bareword.
    See noetl/ai-meta#20.

    Heuristics (all liberal — false-positive cost is leaving template-
    looking strings unredacted, false-negative cost is breaking
    playbooks like above):

    - Contains Jinja markers: ``{{`` / ``}}``.
    - Contains Python f-string or .format markers inside a URL-like
      query parameter, identifiable as the substring sequence
      ``={`` (an ``=`` immediately followed by ``{`` — see
      ``key={urllib...}``).
    - Contains source-code patterns: ``def `` / ``import `` /
      ``return ``.  The python-tool ``code`` field always contains at
      least one of these.
    """
    if not isinstance(value, str) or not value:
        return False
    if "{{" in value or "}}" in value:
        return True
    if "={" in value:
        return True
    for marker in ("def ", "import ", "return ", "class ", "async def "):
        if marker in value:
            return True
    return False


def _is_response_secret_value(value: str, secret_values: Set[str]) -> bool:
    if not isinstance(value, str) or not value:
        return False

    if value in secret_values:
        return True
    for secret in secret_values:
        if len(secret) >= 8 and secret in value:
            return True

    # Template / code-shaped strings skip the structural value-shape
    # checks below.  They can still be flagged as secrets by the
    # explicit ``secret_values`` set above (e.g. when a known token
    # appears as a substring), but the URL-credential and
    # SECRET_VALUE_PATTERNS regex checks would otherwise produce
    # destructive false positives on f-string URL builders and
    # multi-line python code blocks.  See ``_looks_like_template_or_code``
    # docstring + noetl/ai-meta#20.
    if _looks_like_template_or_code(value):
        return False

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


def _is_noetl_keychain_placeholder(value: Any) -> bool:
    """Return ``True`` when ``value`` is a ``$noetl_ref`` keychain reference
    dict produced by ``render_preserving_keychain_refs``.

    The placeholder shape is:

        {"$noetl_ref": {"kind": "keychain", "name": "<name>", "field": "<field>"}}

    These placeholders are storage-safe by design — they carry the
    credential's *name* (which is metadata, already in the keychain manifest
    anyway), not the resolved value.  The worker dereferences them against
    ``noetl.keychain`` at tool-execution time.  Scrubbers MUST pass them
    through; redacting them to ``[REDACTED]`` destroys the only signal the
    worker has that this field needs late-resolution.

    Implemented inline (no import of ``credential_refs``) to avoid a
    circular dependency between ``sanitize`` and ``credential_refs``.
    """
    if not isinstance(value, dict):
        return False
    ref = value.get("$noetl_ref")
    if not isinstance(ref, dict):
        return False
    return ref.get("kind") == "keychain"


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
            caller_blind_redact = key_normalized in additional_keys
            partial_match_sensitive = _is_response_sensitive_key(key_text)
            if caller_blind_redact:
                # The caller explicitly named this key as one that always
                # carries a credential value (HTTP header keys like
                # ``authorization`` / ``cookie`` / ``x_api_key``, or
                # keychain manifest namespaces like ``openai_token``).
                # Blind-redact the value regardless of shape — this is
                # the producer-scrub contract and the response sanitizer
                # honors it verbatim.
                #
                # **Exception**: ``$noetl_ref`` keychain placeholder dicts
                # produced by ``render_preserving_keychain_refs`` are
                # storage-safe references, not resolved values.  Replacing
                # them with ``[REDACTED]`` destroys the worker's only
                # signal that the field needs late-resolution and the
                # downstream tool ends up with ``Authorization: Bearer
                # [REDACTED]`` against the upstream API (concrete failure
                # in noetl/ai-meta#24 — Duffel returned
                # ``access_token_not_found`` 401 on every dispatch
                # despite the keychain cache being correctly populated).
                # Pass the placeholder through so the worker resolves it.
                if _is_noetl_keychain_placeholder(value):
                    result[key] = value
                else:
                    result[key] = redaction
            elif partial_match_sensitive:
                # The key name *partial-matches* an entry in
                # ``SENSITIVE_KEYS`` / ``RESPONSE_SENSITIVE_KEYS`` but
                # the caller did NOT explicitly list it.  This is the
                # path that historically destroyed credential alias
                # references: a key like ``db_credential`` partial-matches
                # ``credential``; a postgres task ``auth`` field exact-
                # matches ``auth``.  Their values are alias names
                # (``pg_auth``, ``openai_session``, ...) used by the
                # NoETL keychain to look up actual secrets at tool-
                # execution time.  Blindly redacting them breaks every
                # downstream credential lookup.
                #
                # Concrete failure on the noetl-demo GKE cluster (the
                # auth0_login_optimized playbook):
                #   - command.issued event stores ``auth: "{{ db_credential }}"``
                #     (raw Jinja template, untouched).
                #   - Worker claims the command and fetches the
                #     externalized ``render_context`` via
                #     ``/api/temp/{execution_id}/{name}`` or
                #     ``/api/result/...`` — both response endpoints run
                #     ``redact_keychain_values`` over the payload.
                #   - Pre-fix, ``redact_keychain_values`` saw
                #     ``db_credential: "pg_auth"`` in render_context,
                #     partial-matched ``credential``, and replaced the
                #     value with ``"[REDACTED]"`` regardless of shape.
                #   - Jinja then rendered ``{{ db_credential }}`` →
                #     ``"[REDACTED]"`` and the worker's auth resolver
                #     called ``GET /api/credentials/[REDACTED]`` which
                #     404'd.  See ``worker/auth_resolver.py:434``
                #     traceback: ``Auth resolution failed for 'auth':
                #     Credential '[REDACTED]' not found``.
                #
                # Strategy for the partial-match case:
                #   - String values: only redact when
                #     ``_is_response_secret_value`` matches (caller-supplied
                #     secrets set, URL credentials, SECRET_VALUE_PATTERNS:
                #     Bearer / Basic / JWT / sk-/sk-ant-/AIza/ya29/
                #     gh{p,o,u,s,r}_/github_pat_/xox{baprs}-/PEM headers /
                #     long random query-string secrets).  Short
                #     identifier-shaped strings pass through.
                #   - Nested dict / list / tuple values: preserve the
                #     prior broad redaction — key-only inspection cannot
                #     reach individual leaves without re-encountering
                #     the same key trap.
                #   - Other scalars (int, bool, None): pass through.
                if isinstance(value, str):
                    if _is_response_secret_value(value, secret_values):
                        result[key] = redaction
                    else:
                        result[key] = value
                elif _is_noetl_keychain_placeholder(value):
                    # Storage-safe $noetl_ref placeholder; preserve so
                    # the worker can resolve.  See the blind-redact
                    # branch above for the failure case this prevents.
                    result[key] = value
                elif isinstance(value, (dict, list, tuple)):
                    result[key] = redaction
                else:
                    result[key] = value
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
            caller_blind_redact = isinstance(key, str) and key.lower() in additional_keys
            partial_match_sensitive = _is_sensitive_key(key)
            if caller_blind_redact:
                # Caller named this key explicitly — blind-redact regardless
                # of value shape.  This is how producer-scrub passes HTTP
                # header conventions (Authorization / Cookie / X-API-Key /
                # ...) through additional_keys; those values are
                # credentials by HTTP convention even when they're short.
                result[key] = redaction
            elif partial_match_sensitive:
                # The key name partial-matches ``SENSITIVE_KEYS`` but the
                # caller did NOT explicitly list it.  This is the path
                # that historically destroyed credential alias references:
                # ``db_credential`` matches ``credential``, postgres task
                # ``auth`` exact-matches ``auth`` — but the values are
                # alias names (``pg_auth``, ``openai_session``, ...) that
                # the NoETL keychain uses to look up actual secrets at
                # tool-execution time.  Blindly redacting them breaks
                # every downstream credential lookup.
                #
                # Concrete failure on the noetl-demo GKE cluster (the
                # auth0_login_optimized playbook):
                #   - workload ``db_credential: pg_auth`` (alias)
                #   - step ``auth: "{{ db_credential }}"`` renders to
                #     ``auth: "pg_auth"``
                #   - Pre-fix the broker sanitizer rewrote that to
                #     ``auth: "[REDACTED]"`` and the worker's auth resolver
                #     looked up ``GET /api/credentials/[REDACTED]`` →
                #     404.  See ``worker/auth_resolver.py:434`` trace:
                #     ``Auth resolution failed for 'auth': Credential
                #     '[REDACTED]' not found``.
                #
                # Strategy for the partial-match case:
                #   - String values: only redact when ``_is_sensitive_value``
                #     matches (Bearer / JWT / long random / PEM / API key
                #     shapes).  Short identifier-shaped strings pass
                #     through — they're alias references, not secrets.
                #   - Nested dict / list values: preserve the prior broad
                #     redaction; recursion cannot value-check leaves
                #     without re-encountering the same key trap.
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
