"""
Unit tests for noetl.worker.keychain_resolver.

Covers:
- extract_keychain_references_from_dict: both Jinja-template strings and
  $noetl_ref dicts emitted by render_preserving_keychain_refs.
- populate_keychain_context: early-exit guard (has_keychain_ref) correctly
  fires for $noetl_ref shapes so the resolver is actually called.
"""

import pytest

from noetl.worker.keychain_resolver import (
    extract_keychain_references_from_dict,
    populate_keychain_context,
)
from noetl.core.credential_refs import NOETL_REF_KEY


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _noetl_ref(name: str, field: str) -> dict:
    """Build the $noetl_ref placeholder shape produced by render_preserving_keychain_refs."""
    return {NOETL_REF_KEY: {"kind": "keychain", "name": name, "field": field}}


# ---------------------------------------------------------------------------
# extract_keychain_references_from_dict
# ---------------------------------------------------------------------------


class TestExtractKeychainReferencesFromDict:
    """extract_keychain_references_from_dict extracts names from both wire formats."""

    def test_jinja_string_top_level(self):
        data = {"token": "{{ keychain.duffel_token.token }}"}
        assert extract_keychain_references_from_dict(data) == {"duffel_token"}

    def test_noetl_ref_dict_top_level(self):
        """$noetl_ref at top level of input dict is recognized."""
        data = {"token": _noetl_ref("duffel_token", "token")}
        assert extract_keychain_references_from_dict(data) == {"duffel_token"}

    def test_noetl_ref_dict_nested(self):
        """$noetl_ref nested inside an outer dict is recognized."""
        data = {"input": {"api_key": _noetl_ref("openai_token", "api_key")}}
        assert extract_keychain_references_from_dict(data) == {"openai_token"}

    def test_mixed_jinja_and_noetl_ref(self):
        """Both wire formats in the same structure yield both names."""
        data = {
            "duffel_token": _noetl_ref("duffel_token", "token"),
            "header": "Bearer {{ keychain.amadeus_token.access_token }}",
        }
        assert extract_keychain_references_from_dict(data) == {"duffel_token", "amadeus_token"}

    def test_noetl_ref_in_list(self):
        data = [_noetl_ref("duffel_token", "token"), "plain string"]
        assert extract_keychain_references_from_dict(data) == {"duffel_token"}

    def test_non_keychain_noetl_ref_ignored(self):
        """$noetl_ref with kind != 'keychain' must not be included."""
        data = {NOETL_REF_KEY: {"kind": "result_ref", "name": "some_name", "field": "value"}}
        assert extract_keychain_references_from_dict(data) == set()

    def test_empty_dict_returns_empty_set(self):
        assert extract_keychain_references_from_dict({}) == set()

    def test_plain_string_no_keychain_returns_empty(self):
        assert extract_keychain_references_from_dict("no references here") == set()

    def test_noetl_ref_without_name_returns_empty(self):
        data = {NOETL_REF_KEY: {"kind": "keychain", "field": "token"}}  # no "name"
        assert extract_keychain_references_from_dict(data) == set()

    def test_credential_ref_kind(self):
        """credential_ref kind used by the duffel playbook resolves to keychain storage."""
        # The duffel playbook sets kind: credential_ref; after server-side processing
        # the stored entry is referenced by a $noetl_ref with kind=keychain.
        data = {"duffel_token": _noetl_ref("duffel_token", "token")}
        refs = extract_keychain_references_from_dict(data)
        assert "duffel_token" in refs

    def test_deeply_nested_noetl_ref(self):
        data = {"a": {"b": {"c": _noetl_ref("deep_token", "secret")}}}
        assert extract_keychain_references_from_dict(data) == {"deep_token"}


# ---------------------------------------------------------------------------
# populate_keychain_context — has_keychain_ref guard
# ---------------------------------------------------------------------------


class TestPopulateKeychainContextNoetlRef:
    """
    populate_keychain_context must call resolve_keychain_entries when task_config
    contains $noetl_ref dicts (not just raw Jinja strings).

    Before the fix, has_keychain_ref returned False for $noetl_ref shapes, so
    populate_keychain_context exited early and the resolver was never called.
    """

    @pytest.mark.asyncio
    async def test_noetl_ref_in_input_triggers_resolution(self, monkeypatch):
        """
        When task_config["input"] contains a $noetl_ref dict the resolver must
        be invoked and the keychain populated in context.
        """
        resolved_calls = []

        async def fake_resolve_keychain_entries(keychain_refs, catalog_id, **_kwargs):
            resolved_calls.append(set(keychain_refs))
            return {"duffel_token": {"token": "fake-duffel-token"}}

        import noetl.worker.keychain_resolver as kr
        monkeypatch.setattr(kr, "resolve_keychain_entries", fake_resolve_keychain_entries)

        task_config = {
            "input": {
                "duffel_token": _noetl_ref("duffel_token", "token"),
            },
            "code": "result = {'status': 'ok'}",
        }
        context = {"catalog_id": "99", "execution_id": "42"}

        result_context = await populate_keychain_context(
            task_config=task_config,
            context=context,
            catalog_id=99,
        )

        assert resolved_calls, "resolve_keychain_entries was never called — early-exit guard bug"
        assert resolved_calls[0] == {"duffel_token"}
        assert result_context["keychain"]["duffel_token"]["token"] == "fake-duffel-token"

    @pytest.mark.asyncio
    async def test_jinja_string_still_triggers_resolution(self, monkeypatch):
        """Regression guard: Jinja-template strings continue to work after the fix."""
        resolved_calls = []

        async def fake_resolve_keychain_entries(keychain_refs, catalog_id, **_kwargs):
            resolved_calls.append(set(keychain_refs))
            return {"amadeus_token": {"access_token": "fake-amadeus-token"}}

        import noetl.worker.keychain_resolver as kr
        monkeypatch.setattr(kr, "resolve_keychain_entries", fake_resolve_keychain_entries)

        task_config = {
            "input": {
                "token": "{{ keychain.amadeus_token.access_token }}",
            },
        }
        context = {"catalog_id": "77"}

        result_context = await populate_keychain_context(
            task_config=task_config,
            context=context,
            catalog_id=77,
        )

        assert resolved_calls, "resolve_keychain_entries was not called for Jinja template"
        assert "amadeus_token" in result_context["keychain"]

    @pytest.mark.asyncio
    async def test_no_keychain_ref_skips_resolution(self, monkeypatch):
        """When task_config has no keychain refs, the resolver must NOT be called."""
        resolver_called = []

        async def fake_resolve_keychain_entries(**_kwargs):
            resolver_called.append(True)
            return {}

        import noetl.worker.keychain_resolver as kr
        monkeypatch.setattr(kr, "resolve_keychain_entries", fake_resolve_keychain_entries)

        task_config = {"input": {"plain_value": "hello"}, "code": "result = {}"}
        context = {"catalog_id": "1"}

        result_context = await populate_keychain_context(
            task_config=task_config,
            context=context,
            catalog_id=1,
        )

        assert not resolver_called, "resolver should be skipped when there are no keychain refs"
        assert "keychain" not in result_context

    @pytest.mark.asyncio
    async def test_oauth2_amadeus_noetl_ref(self, monkeypatch):
        """
        An amadeus-style oauth2 entry stored as $noetl_ref is also recognized.
        This covers the 'does the amadeus fix still work?' open question.
        """
        resolved_calls = []

        async def fake_resolve_keychain_entries(keychain_refs, catalog_id, **_kwargs):
            resolved_calls.append(set(keychain_refs))
            return {"amadeus_token": {"access_token": "fake-amadeus", "token_type": "Bearer"}}

        import noetl.worker.keychain_resolver as kr
        monkeypatch.setattr(kr, "resolve_keychain_entries", fake_resolve_keychain_entries)

        task_config = {
            "input": {
                "amadeus_token": _noetl_ref("amadeus_token", "access_token"),
            },
        }
        context = {}

        result_context = await populate_keychain_context(
            task_config=task_config,
            context=context,
            catalog_id=55,
        )

        assert resolved_calls and "amadeus_token" in resolved_calls[0]
        assert result_context["keychain"]["amadeus_token"]["access_token"] == "fake-amadeus"
