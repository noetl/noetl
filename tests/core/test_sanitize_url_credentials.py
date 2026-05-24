"""Unit tests for :func:`noetl.core.sanitize.redact_url_credentials`.

Driven by the GKE diagnostic round
(handoffs/archive/2026-05-23-gke-worker-consumer-missing): worker
startup logs were emitting NATS connection strings with embedded
``user:password@`` credentials, which then shipped to VictoriaLogs.
The redaction helper closes that leak; these tests pin the contract.
"""

from __future__ import annotations

import pytest

from noetl.core.sanitize import REDACTED, redact_url_credentials


def test_redacts_nats_userinfo():
    assert (
        redact_url_credentials("nats://noetl:noetl@nats.nats.svc.cluster.local:4222")
        == f"nats://{REDACTED}@nats.nats.svc.cluster.local:4222"
    )


def test_redacts_postgres_userinfo():
    assert (
        redact_url_credentials("postgres://noetl:secret@postgres.noetl.svc:5432/noetl")
        == f"postgres://{REDACTED}@postgres.noetl.svc:5432/noetl"
    )


def test_redacts_http_basic_auth_userinfo():
    assert (
        redact_url_credentials("https://admin:hunter2@api.example.com/v1")
        == f"https://{REDACTED}@api.example.com/v1"
    )


def test_redacts_user_only_userinfo():
    """user@host with no password is still userinfo and should be redacted."""
    assert (
        redact_url_credentials("nats://noetl@nats:4222")
        == f"nats://{REDACTED}@nats:4222"
    )


def test_passthrough_when_no_userinfo():
    assert (
        redact_url_credentials("nats://nats.nats.svc.cluster.local:4222")
        == "nats://nats.nats.svc.cluster.local:4222"
    )
    assert (
        redact_url_credentials("http://noetl.noetl.svc.cluster.local:8082")
        == "http://noetl.noetl.svc.cluster.local:8082"
    )


def test_redacts_url_embedded_in_log_line():
    """The worker startup line embeds the URL in prose — patcher should
    catch URLs found anywhere in the string, not just at the start."""
    msg = (
        "Starting Core worker worker-c8384760 | "
        "NATS=nats://noetl:noetl@nats:4222 | "
        "Server=http://noetl.noetl.svc:8082"
    )
    out = redact_url_credentials(msg)
    assert "noetl:noetl@" not in out
    assert f"nats://{REDACTED}@nats:4222" in out
    # http://noetl... has no userinfo, so it must pass through unchanged
    assert "http://noetl.noetl.svc:8082" in out


def test_redacts_multiple_urls_in_one_string():
    msg = "primary=postgres://u1:p1@db1/x replica=postgres://u2:p2@db2/x"
    out = redact_url_credentials(msg)
    assert "u1:p1@" not in out
    assert "u2:p2@" not in out
    assert out.count(f"postgres://{REDACTED}@") == 2


def test_idempotent_when_already_redacted():
    once = redact_url_credentials("nats://noetl:noetl@nats:4222")
    twice = redact_url_credentials(once)
    assert once == twice


def test_non_string_inputs_passthrough():
    """Helper is documented as passing non-string inputs through unchanged."""
    assert redact_url_credentials(None) is None
    assert redact_url_credentials(42) == 42
    assert redact_url_credentials(["nats://a:b@c"]) == ["nats://a:b@c"]


def test_custom_placeholder():
    out = redact_url_credentials(
        "nats://noetl:noetl@nats:4222", placeholder="***"
    )
    assert out == "nats://***@nats:4222"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "no urls here",
        "just-a-host-no-scheme.example.com",
        "nats://",  # malformed; no host
        "user:password@host",  # missing scheme
    ],
)
def test_passthrough_for_edge_cases(value: str):
    assert redact_url_credentials(value) == value
