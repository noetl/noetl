"""Unit tests for the catalog kind-precedence helper.

The DB-backed register_resource path is exercised by integration tests;
these focus on the pure resolution logic so a regression in the
"YAML kind: is authoritative" rule is caught without standing up
Postgres.
"""

from __future__ import annotations

import pytest

from noetl.server.api.catalog.service import CatalogService


# ---------------------------------------------------------------------------
# Payload kind wins over the request parameter
# ---------------------------------------------------------------------------


def test_payload_mcp_kind_overrides_default_playbook_fallback():
    """An ``kind: Mcp`` template registered via the catch-all
    ``catalog register`` (which the CLI sends as resource_type="Playbook")
    must land in the catalog as kind=mcp, not kind=playbook.
    """
    payload = {"kind": "Mcp", "metadata": {"path": "mcp/kubernetes"}, "spec": {}}
    assert CatalogService._resolve_resource_kind(
        payload=payload,
        fallback="Playbook",
    ) == "mcp"


def test_payload_kind_aliases_normalised():
    """All recognised aliases collapse through _normalize_resource_type."""
    cases = [
        ("Playbook", "playbook"),
        ("Mcp", "mcp"),
        ("MCP", "mcp"),
        ("ModelContextProtocol", "mcp"),
        ("Agent", "agent"),
        ("Credential", "credential"),
        ("Memory", "memory"),
    ]
    for raw, expected in cases:
        payload = {"kind": raw}
        assert (
            CatalogService._resolve_resource_kind(payload=payload, fallback="Playbook")
            == expected
        ), f"kind={raw!r} should normalise to {expected!r}"


def test_payload_kind_with_surrounding_whitespace_is_used():
    """A whitespace-surrounded but non-empty kind should still beat the fallback."""
    payload = {"kind": "  Mcp  "}
    assert CatalogService._resolve_resource_kind(
        payload=payload,
        fallback="Playbook",
    ) == "mcp"


# ---------------------------------------------------------------------------
# Fallback to request parameter
# ---------------------------------------------------------------------------


def test_missing_payload_kind_falls_back_to_parameter():
    """Older YAMLs without an explicit kind: still register correctly via the parameter."""
    payload = {"metadata": {"path": "x"}, "spec": {}}
    assert CatalogService._resolve_resource_kind(
        payload=payload,
        fallback="Playbook",
    ) == "playbook"
    assert CatalogService._resolve_resource_kind(
        payload=payload,
        fallback="Mcp",
    ) == "mcp"


def test_blank_payload_kind_falls_back_to_parameter():
    payload = {"kind": "", "metadata": {"path": "x"}}
    assert CatalogService._resolve_resource_kind(
        payload=payload,
        fallback="Playbook",
    ) == "playbook"

    payload = {"kind": "   "}
    assert CatalogService._resolve_resource_kind(
        payload=payload,
        fallback="Mcp",
    ) == "mcp"


def test_non_string_payload_kind_falls_back_to_parameter():
    """Defensive: an integer / list / dict in `kind:` shouldn't crash the resolver."""
    for bad in (42, ["Mcp"], {"name": "Mcp"}):
        assert CatalogService._resolve_resource_kind(
            payload={"kind": bad},
            fallback="Playbook",
        ) == "playbook"


def test_non_dict_payload_falls_back_to_parameter():
    """An empty / scalar / list YAML body shouldn't crash — treat as no payload kind."""
    for payload in (None, "", [], "scalar", 123):
        assert CatalogService._resolve_resource_kind(
            payload=payload,
            fallback="Mcp",
        ) == "mcp"


# ---------------------------------------------------------------------------
# Both empty -> default playbook (preserves prior behaviour)
# ---------------------------------------------------------------------------


def test_empty_payload_and_blank_fallback_uses_default_playbook():
    assert CatalogService._resolve_resource_kind(
        payload={},
        fallback=None,
    ) == "playbook"
    assert CatalogService._resolve_resource_kind(
        payload={},
        fallback="",
    ) == "playbook"
