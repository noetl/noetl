"""Tests for API response redaction at serialization boundaries."""

from __future__ import annotations

import pytest

from noetl.core.sanitize import REDACTED, redact_keychain_values


def _jwt() -> str:
    return ".".join(["eyJhbGciOiJIUzI1NiJ9", "eyJzdWIiOiIxMjMifQ", "signature"])


def _provider_key() -> str:
    return "sk-" + "test_" + ("A" * 32)


def _url_with_key() -> str:
    return "https://example.invalid/static?key=" + ("B" * 32)


def test_redacts_keychain_nested_values_by_key():
    payload = {
        "variables": {
            "keychain": {
                "openai_token": {
                    "api_key": _provider_key(),
                }
            },
            "safe_region": "us-central1",
        }
    }

    redacted = redact_keychain_values(payload)

    assert redacted["variables"]["keychain"] == REDACTED
    assert redacted["variables"]["safe_region"] == "us-central1"


def test_redacts_user_bearer_and_jwt_values():
    payload = {
        "auth0_token": _jwt(),
        "headers": {"Authorization": "Bearer " + ("C" * 48)},
    }

    redacted = redact_keychain_values(payload)

    assert redacted["auth0_token"] == REDACTED
    assert redacted["headers"]["Authorization"] == REDACTED


def test_redacts_secret_shaped_intermediate_values_without_secret_key():
    payload = {
        "provider_response": {
            "image_url": _url_with_key(),
            "notes": "public",
        }
    }

    redacted = redact_keychain_values(payload)

    assert redacted["provider_response"]["image_url"] == REDACTED
    assert redacted["provider_response"]["notes"] == "public"


def test_redacts_known_secret_values_embedded_in_text():
    secret = "opaque-secret-value"
    payload = {"message": f"provider returned {secret}"}

    redacted = redact_keychain_values(payload, secret_values={secret})

    assert redacted["message"] == REDACTED


def test_redaction_is_idempotent():
    payload = {"token": _jwt(), "nested": [{"api_key": _provider_key()}]}

    once = redact_keychain_values(payload)
    twice = redact_keychain_values(once)

    assert once == twice


@pytest.mark.parametrize("value", [None, 42, True, "plain text", {"region": "Miami"}])
def test_non_secret_values_passthrough(value):
    assert redact_keychain_values(value) == value


# ---------------------------------------------------------------------------
# Regression tests for the credential-alias preservation fix.  See the long
# header comment in ``_redact_response_recursive`` (noetl/core/sanitize.py)
# for the failure mode this guards against.  Mirror tests live in
# tests/core/test_sanitize_sensitive_data.py for the write-side sanitizer
# under the same partial-key-match trap.
# ---------------------------------------------------------------------------


def test_preserves_postgres_auth_alias():
    """Render-context fetches surfaced ``auth: 'pg_auth'`` to the worker.
    Pre-fix the response redactor saw the ``auth`` key, blindly redacted
    the value, and the worker's auth resolver looked up
    ``GET /api/credentials/[REDACTED]`` which 404'd."""
    payload = {"auth": "pg_auth", "kind": "postgres", "command": "SELECT 1"}
    assert redact_keychain_values(payload) == payload


def test_preserves_db_credential_workload_alias():
    """``db_credential`` partial-matches ``credential`` in
    ``SENSITIVE_KEYS``.  The value ``pg_auth`` is a short alias name."""
    assert redact_keychain_values({"db_credential": "pg_auth"}) == {
        "db_credential": "pg_auth"
    }


def test_preserves_nats_credential_alias():
    """Same pattern for any downstream-resolved credential reference."""
    payload = {
        "nats_credential": "nats_user",
        "auth0_credential": "auth0_client",
        "oauth_token": "session_alias",
    }
    assert redact_keychain_values(payload) == payload


def test_redacts_bearer_token_under_auth_key():
    """Real Bearer tokens still get redacted regardless of key name."""
    payload = {"auth": "Bearer " + ("D" * 32)}
    assert redact_keychain_values(payload) == {"auth": REDACTED}


def test_redacts_jwt_under_token_key():
    payload = {"token": _jwt()}
    assert redact_keychain_values(payload) == {"token": REDACTED}


def test_caller_supplied_secret_still_redacts_short_alias_shaped_value():
    """When the caller passes ``secret_values={'pg_auth'}``, an exact match
    on the alias-shaped string is treated as a known secret and redacted.
    This is the legitimate value-based escape hatch."""
    redacted = redact_keychain_values(
        {"auth": "pg_auth"}, secret_values={"pg_auth"}
    )
    assert redacted == {"auth": REDACTED}


def test_nested_dict_under_sensitive_key_blanket_redacted():
    """Nested structures under a sensitive key still get blanket-redacted —
    we cannot value-check individual leaves without re-encountering the
    same key trap on the way down."""
    payload = {"credentials": {"username": "admin", "password": "real_secret"}}
    assert redact_keychain_values(payload) == {"credentials": REDACTED}


def test_nested_list_under_sensitive_key_blanket_redacted():
    payload = {"tokens": ["t1", "t2", "t3"]}
    assert redact_keychain_values(payload) == {"tokens": REDACTED}


def test_non_string_scalars_under_sensitive_keys_pass_through():
    """ints, bools, None under sensitive keys cannot be credentials."""
    payload = {
        "token_expiry": 3600,
        "is_credential_present": True,
        "refresh_token": None,
    }
    assert redact_keychain_values(payload) == payload


def test_render_context_workload_with_aliases_and_real_secret():
    """End-to-end shape: the workload dict the worker fetches via
    ``/api/temp/{execution_id}/{name}`` for Jinja rendering.  Aliases
    must survive; a real Bearer token in a leaf still redacts."""
    render_context = {
        "workload": {
            "db_credential": "pg_auth",
            "nats_credential": "nats_user",
            "auth0_token": "Bearer " + ("E" * 32),
            "request_id": "abc-123",
        },
    }
    redacted = redact_keychain_values(render_context)
    assert redacted["workload"]["db_credential"] == "pg_auth"
    assert redacted["workload"]["nats_credential"] == "nats_user"
    assert redacted["workload"]["auth0_token"] == REDACTED
    assert redacted["workload"]["request_id"] == "abc-123"


def test_preserves_noetl_ref_placeholder_under_blind_redact_key():
    """``$noetl_ref`` keychain placeholders must survive blind-redact branch.

    Regression test for noetl/ai-meta#24 — the producer scrub previously
    replaced ``{"duffel_token": {"$noetl_ref": ...}}`` with
    ``{"duffel_token": "[REDACTED]"}`` because the key ``duffel_token``
    was in ``additional_keys`` (derived from the keychain manifest).
    The worker then received a string sentinel where the placeholder
    dict should have been, sent ``Authorization: Bearer [REDACTED]``
    to Duffel, and got ``access_token_not_found`` 401 on every dispatch.
    """
    payload = {
        "duffel_token": {
            "$noetl_ref": {
                "kind": "keychain",
                "name": "duffel_token",
                "field": "token",
            }
        }
    }

    redacted = redact_keychain_values(payload, additional_keys={"duffel_token"})

    assert redacted["duffel_token"] == payload["duffel_token"]


def test_preserves_noetl_ref_placeholder_under_partial_match_key():
    """Same preservation contract for the partial-match-sensitive branch.

    ``access_token`` is partial-match-sensitive via the ``token``
    substring rule.  When the value is a ``$noetl_ref`` placeholder
    (e.g. amadeus's ``{{ keychain.amadeus_token.access_token }}``
    encoded via ``render_preserving_keychain_refs``) the redactor
    used to replace it with ``[REDACTED]``.  Now it passes through.
    """
    payload = {
        "access_token": {
            "$noetl_ref": {
                "kind": "keychain",
                "name": "amadeus_token",
                "field": "access_token",
            }
        }
    }

    # No additional_keys — the partial-match branch handles ``access_token``
    # via the substring rule.
    redacted = redact_keychain_values(payload)

    assert redacted["access_token"] == payload["access_token"]


def test_still_redacts_resolved_token_string_under_blind_redact_key():
    """Real credential values must still be redacted — the preservation
    only applies to ``$noetl_ref`` placeholder dicts.
    """
    payload = {
        "duffel_token": "duffel_test_resolvedSecretValue",
    }

    redacted = redact_keychain_values(payload, additional_keys={"duffel_token"})

    assert redacted["duffel_token"] == REDACTED


def test_redacts_noetl_ref_with_non_keychain_kind():
    """Only ``kind: keychain`` placeholders survive.  Other ``$noetl_ref``
    shapes (if any are introduced later) must be redacted by default
    until they're explicitly opted into the preservation list.
    """
    payload = {
        "duffel_token": {
            "$noetl_ref": {
                "kind": "something_else",
                "name": "foo",
            }
        }
    }

    redacted = redact_keychain_values(payload, additional_keys={"duffel_token"})

    assert redacted["duffel_token"] == REDACTED


def test_redacts_dict_without_noetl_ref_under_blind_redact_key():
    """Any other dict shape under a blind-redact key is still redacted
    — the preservation is narrow to the placeholder contract.
    """
    payload = {
        "duffel_token": {
            "nested": "leaked-token-value",
        }
    }

    redacted = redact_keychain_values(payload, additional_keys={"duffel_token"})

    assert redacted["duffel_token"] == REDACTED
