"""Tests for ``noetl.core.sanitize.sanitize_sensitive_data``.

The bulk of these tests cover the production-hotfix regression where the
sanitizer was destroying credential alias references (workload values used by
the NoETL keychain to look up actual secrets at tool-execution time).  The
sanitizer must NOT redact a short identifier-shaped string just because the
key name partial-matches an entry in ``SENSITIVE_KEYS``.
"""

from __future__ import annotations

import pytest

from noetl.core.sanitize import REDACTED, sanitize_sensitive_data


class TestCredentialAliasPassThrough:
    """Credential aliases are short identifier-shaped strings stored under
    sensitive-named keys.  They must survive sanitization because the worker
    needs them to look up the actual secret via the credential API."""

    def test_postgres_auth_field_with_alias(self):
        """The postgres tool's ``auth`` field holds a credential alias name,
        not the credential value.  Pre-fix, ``auth: "pg_auth"`` became
        ``auth: "[REDACTED]"`` and the worker's
        ``GET /api/credentials/[REDACTED]`` 404'd, breaking every playbook
        that routes a credential by alias."""
        task = {"kind": "postgres", "auth": "pg_auth", "command": "SELECT 1"}
        result = sanitize_sensitive_data(task)
        assert result == {
            "kind": "postgres",
            "auth": "pg_auth",
            "command": "SELECT 1",
        }

    def test_workload_db_credential_alias(self):
        """Workload values use ``db_credential`` as the variable name holding
        a credential alias.  ``db_credential`` partial-matches ``credential``
        in SENSITIVE_KEYS, but the value is just an alias string."""
        workload = {"db_credential": "pg_auth"}
        assert sanitize_sensitive_data(workload) == {"db_credential": "pg_auth"}

    def test_workload_nats_credential_alias(self):
        """Same pattern for NATS / Auth0 / other downstream-resolved
        credentials."""
        workload = {
            "db_credential": "pg_auth",
            "nats_credential": "nats_user",
            "auth0_credential": "auth0_client",
        }
        assert sanitize_sensitive_data(workload) == workload

    def test_oauth_token_field_with_alias(self):
        """``oauth_token`` partial-matches ``token``; a short alias value
        like ``auth0_jwt`` must pass through."""
        assert sanitize_sensitive_data({"oauth_token": "auth0_jwt"}) == {
            "oauth_token": "auth0_jwt"
        }


class TestRealSecretsStillRedacted:
    """The relaxation must NOT widen the leak surface for actual secret
    values.  ``_is_sensitive_value`` patterns still catch realistic
    credentials regardless of key name."""

    def test_bearer_token(self):
        result = sanitize_sensitive_data({"auth": "Bearer abc123def456ghi789"})
        assert result == {"auth": REDACTED}

    def test_basic_auth_header(self):
        result = sanitize_sensitive_data({"authorization": "Basic dXNlcjpwYXNz"})
        assert result == {"authorization": REDACTED}

    def test_jwt_token(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        result = sanitize_sensitive_data({"id_token": jwt})
        assert result == {"id_token": REDACTED}

    def test_long_alphanumeric_api_key(self):
        """``_is_sensitive_value`` matches ``[A-Za-z0-9]{32,}`` for generic
        API key shapes."""
        api_key = "abcdef1234567890abcdef1234567890abc"  # 35 chars
        result = sanitize_sensitive_data({"api_key": api_key})
        assert result == {"api_key": REDACTED}

    def test_aws_secret_access_key(self):
        """40-char AWS-shaped secret pattern."""
        aws_secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        assert len(aws_secret) == 40
        result = sanitize_sensitive_data({"aws_secret_access_key": aws_secret})
        assert result == {"aws_secret_access_key": REDACTED}

    def test_pem_private_key(self):
        pem = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEA...\n"
            "-----END RSA PRIVATE KEY-----"
        )
        result = sanitize_sensitive_data({"private_key": pem})
        assert result == {"private_key": REDACTED}


class TestNestedStructureRedaction:
    """Nested dicts/lists under a sensitive key still get blanket-redacted —
    we cannot value-check individual leaves without re-encountering the same
    sensitive-key trap on the way down."""

    def test_credentials_dict_redacted(self):
        data = {"credentials": {"username": "admin", "password": "real_secret"}}
        assert sanitize_sensitive_data(data) == {"credentials": REDACTED}

    def test_token_list_redacted(self):
        data = {"tokens": ["t1", "t2", "t3"]}
        assert sanitize_sensitive_data(data) == {"tokens": REDACTED}


class TestNonStringScalarsUnderSensitiveKeys:
    """Non-string scalars (int, bool, None) under sensitive keys pass through
    as-is — they cannot be secrets in any realistic credential format."""

    def test_int_under_sensitive_key(self):
        assert sanitize_sensitive_data({"token_expiry": 3600}) == {
            "token_expiry": 3600
        }

    def test_bool_under_sensitive_key(self):
        assert sanitize_sensitive_data({"is_credential_present": True}) == {
            "is_credential_present": True
        }

    def test_none_under_sensitive_key(self):
        assert sanitize_sensitive_data({"refresh_token": None}) == {
            "refresh_token": None
        }


class TestDeepWorkloadStructure:
    """End-to-end: a typical NoETL playbook command context with workload +
    rendered task config + meta.  The sanitizer must produce a clean payload
    that preserves every alias reference."""

    def test_command_context_with_aliases_and_nested_secret(self):
        context = {
            "workload": {
                "db_credential": "pg_auth",
                "nats_credential": "nats_user",
                "request_id": "abc-123",
            },
            "tool_config": {
                "kind": "postgres",
                "auth": "pg_auth",
                "command": "SELECT * FROM users WHERE id = %s",
            },
            "render_context": {
                # Resolved keychain values that DID reach a leaf — the
                # producer scrub layer normally catches these upstream, but
                # the sensitive-value pattern is the secondary defence.
                "secret": "Bearer eyJhbGciOiJIUzI1NiJ9.abc.def",
            },
        }
        result = sanitize_sensitive_data(context)
        # Aliases preserved
        assert result["workload"]["db_credential"] == "pg_auth"
        assert result["workload"]["nats_credential"] == "nats_user"
        assert result["workload"]["request_id"] == "abc-123"
        # Postgres tool config alias preserved
        assert result["tool_config"]["auth"] == "pg_auth"
        # Bearer token redacted
        assert result["render_context"]["secret"] == REDACTED
