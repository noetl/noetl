"""Unit tests for the catalog kind-precedence helper + register-time validation.

The DB-backed register_resource path is exercised by integration tests;
these focus on the pure resolution + validation logic so regressions in
the "YAML kind: is authoritative" rule and the Pydantic validation
gate are caught without standing up Postgres.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

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


# ---------------------------------------------------------------------------
# _validate_payload — register-time Pydantic validation
# ---------------------------------------------------------------------------


def _valid_playbook_dict():
    """Minimal v10 playbook that passes Pydantic validation."""
    return {
        "apiVersion": "noetl.io/v2",
        "kind": "Playbook",
        "metadata": {"name": "test_pb", "path": "tests/fixtures/test_pb"},
        "workflow": [
            {
                "step": "start",
                "tool": {"kind": "noop"},
                "next": {
                    "spec": {"mode": "exclusive"},
                    "arcs": [{"step": "end"}],
                },
            },
            {"step": "end", "tool": {"kind": "noop"}},
        ],
    }


def test_validate_payload_skips_non_playbook_kinds():
    """mcp / credential / memory kinds skip Pydantic validation entirely."""
    for kind in ("mcp", "credential", "memory"):
        # An obviously invalid playbook shouldn't raise — those kinds aren't
        # validated against the Playbook model.
        CatalogService._validate_payload(
            resource_type=kind,
            payload={"apiVersion": "noetl.io/v2", "kind": kind, "metadata": {"name": "x"}},
            path="x",
        )


def test_validate_payload_accepts_valid_playbook():
    CatalogService._validate_payload(
        resource_type="playbook",
        payload=_valid_playbook_dict(),
        path="tests/fixtures/test_pb",
    )


def test_validate_payload_rejects_deprecated_list_form_next():
    """Locks in the regression that motivated this PR.

    The deprecated `next: - step: end` form (an Arc list rather than
    a NextRouter dict) must surface as 422 at register time, not as
    a misleading "Playbook not found" at execute time.
    """
    bad = _valid_playbook_dict()
    bad["workflow"][0]["next"] = [{"step": "end"}]  # the deprecated v9 form

    with pytest.raises(HTTPException) as info:
        CatalogService._validate_payload(
            resource_type="playbook",
            payload=bad,
            path="tests/fixtures/bad_pb",
        )
    assert info.value.status_code == 422
    assert "tests/fixtures/bad_pb" in info.value.detail
    assert "next" in info.value.detail.lower()


def test_validate_payload_rejects_invalid_kind_field():
    """An apiVersion / kind mismatch should also be a 422."""
    bad = _valid_playbook_dict()
    bad["kind"] = "NotAPlaybook"

    with pytest.raises(HTTPException) as info:
        CatalogService._validate_payload(
            resource_type="playbook",
            payload=bad,
            path="x",
        )
    assert info.value.status_code == 422


def test_validate_payload_rejects_non_dict_payload():
    """A YAML body that parses to a list / scalar / None should 422."""
    for bad in ([], "scalar", 42, None):
        with pytest.raises(HTTPException) as info:
            CatalogService._validate_payload(
                resource_type="playbook",
                payload=bad,
                path="x",
            )
        assert info.value.status_code == 422


def test_validate_payload_validates_agents_too():
    """`agent` resources are playbook-shaped — same Pydantic model gates them."""
    bad = _valid_playbook_dict()
    bad["workflow"] = []  # empty workflow trips the validator

    with pytest.raises(HTTPException) as info:
        CatalogService._validate_payload(
            resource_type="agent",
            payload=bad,
            path="x",
        )
    assert info.value.status_code == 422
