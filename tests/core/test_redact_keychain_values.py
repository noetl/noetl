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
