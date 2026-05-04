"""Unit tests for PlaybookMetadata + the Playbook.metadata field validator.

Gap 3 of the NoETL-as-AI-OS architecture spike. Hardens the soft dict
lookup that ``noetl.server.api.mcp.playbook_mcp`` does for
``metadata.exposes_as_mcp``: registration now validates the field
shape (must be bool when present) rather than relying on payload
introspection at MCP-call time.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from noetl.core.dsl.engine.models.executor import (
    Playbook,
    PlaybookMetadata,
)


# ---------------------------------------------------------------------------
# PlaybookMetadata standalone
# ---------------------------------------------------------------------------


class TestPlaybookMetadata:
    """Cover the typed metadata sub-model in isolation."""

    def test_minimal_valid(self):
        m = PlaybookMetadata.model_validate({"name": "amadeus_ai_api"})
        assert m.name == "amadeus_ai_api"
        assert m.exposes_as_mcp is None
        assert m.exposed_in_ui is None
        assert m.tags is None
        assert m.capabilities is None

    def test_name_required(self):
        with pytest.raises(ValidationError) as excinfo:
            PlaybookMetadata.model_validate({})
        assert "name" in str(excinfo.value).lower()

    @pytest.mark.parametrize("value", [True, False])
    def test_exposes_as_mcp_accepts_bool(self, value):
        m = PlaybookMetadata.model_validate({"name": "x", "exposes_as_mcp": value})
        assert m.exposes_as_mcp is value

    @pytest.mark.parametrize("value", ["yes", "true", 1, 0, "false"])
    def test_exposes_as_mcp_rejects_non_bool(self, value):
        with pytest.raises(ValidationError) as excinfo:
            PlaybookMetadata.model_validate({"name": "x", "exposes_as_mcp": value})
        assert "exposes_as_mcp" in str(excinfo.value).lower()

    @pytest.mark.parametrize("value", [True, False])
    def test_exposed_in_ui_accepts_bool(self, value):
        m = PlaybookMetadata.model_validate({"name": "x", "exposed_in_ui": value})
        assert m.exposed_in_ui is value

    def test_tags_string_coerced_to_list(self):
        # Copy-paste YAML often drops the surrounding [...] for single tags;
        # we accept the singleton and wrap rather than rejecting the
        # registration over a trivial mistake.
        m = PlaybookMetadata.model_validate({"name": "x", "tags": "infra"})
        assert m.tags == ["infra"]

    def test_tags_list_pass_through(self):
        m = PlaybookMetadata.model_validate(
            {"name": "x", "tags": ["infra", "observability"]}
        )
        assert m.tags == ["infra", "observability"]

    def test_tags_rejects_non_list_non_string(self):
        with pytest.raises(ValidationError):
            PlaybookMetadata.model_validate({"name": "x", "tags": 42})

    def test_capabilities_list_pass_through(self):
        m = PlaybookMetadata.model_validate(
            {"name": "x", "capabilities": ["code-review", "release-management"]}
        )
        assert m.capabilities == ["code-review", "release-management"]

    def test_unknown_keys_pass_through(self):
        # extra=allow keeps unknown metadata keys reachable; the typed
        # model is a *view* over well-known fields, not a denylist on
        # everything else.
        m = PlaybookMetadata.model_validate(
            {"name": "x", "owner": "team@example.com", "x_custom": 42}
        )
        dumped = m.model_dump()
        assert dumped["owner"] == "team@example.com"
        assert dumped["x_custom"] == 42


# ---------------------------------------------------------------------------
# Playbook.metadata field validator
# ---------------------------------------------------------------------------


_MINIMAL_WORKFLOW = [{"step": "start", "next": [{"step": "end"}]}, {"step": "end"}]


def _playbook(metadata: dict) -> Playbook:
    """Helper to build a Playbook with the given metadata + a no-op flow."""
    return Playbook.model_validate({
        "apiVersion": "noetl.io/v2",
        "kind": "Playbook",
        "metadata": metadata,
        "workflow": _MINIMAL_WORKFLOW,
    })


class TestPlaybookMetadataValidator:
    """Cover the field_validator on Playbook.metadata."""

    def test_metadata_round_trips_as_dict(self):
        # The validator returns the original dict so existing call sites
        # like ``state.playbook.metadata.get("path", ...)`` keep working
        # without a type-shift refactor.
        pb = _playbook({"name": "p", "path": "examples/p"})
        assert isinstance(pb.metadata, dict)
        assert pb.metadata.get("path") == "examples/p"
        assert pb.metadata["name"] == "p"

    def test_invalid_exposes_as_mcp_blocks_register(self):
        with pytest.raises(ValidationError) as excinfo:
            _playbook({"name": "p", "exposes_as_mcp": "yes"})
        assert "exposes_as_mcp" in str(excinfo.value).lower()

    def test_valid_exposes_as_mcp_passes(self):
        pb = _playbook({"name": "p", "exposes_as_mcp": False})
        assert pb.metadata["exposes_as_mcp"] is False

    def test_metadata_must_be_dict(self):
        with pytest.raises(ValidationError) as excinfo:
            _playbook(["not", "a", "dict"])  # type: ignore[arg-type]
        assert "dict" in str(excinfo.value).lower() or "mapping" in str(excinfo.value).lower()
