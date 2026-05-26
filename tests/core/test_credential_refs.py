import pytest
from jinja2 import Environment

from noetl.core.credential_refs import (
    NOETL_REF_KEY,
    build_keychain_manifest,
    encode_keychain_templates,
    is_mixed_keychain_expression,
    parse_pure_keychain_expression,
    render_preserving_keychain_refs,
    resolve_credential_references,
    strip_keychain_namespaces,
)
from noetl.core.dsl.render import render_template


def test_pure_keychain_expression_encodes_as_ref():
    encoded = parse_pure_keychain_expression("{{ keychain.openai_token.api_key | default('') }}")

    assert encoded == {
        NOETL_REF_KEY: {
            "kind": "keychain",
            "name": "openai_token",
            "field": "api_key",
        }
    }


def test_mixed_keychain_expression_is_deferred():
    template = "Bearer {{ keychain.openai_token.api_key }}"

    assert is_mixed_keychain_expression(template) is True
    assert encode_keychain_templates(template) == template


def test_render_preserving_keychain_refs_renders_non_secret_templates_only():
    payload = {
        "region": "{{ workload.region }}",
        "api_key": "{{ keychain.openai_token.api_key | default('') }}",
        "header": "Bearer {{ keychain.openai_token.api_key }}",
    }

    rendered = render_preserving_keychain_refs(
        Environment(),
        payload,
        {"workload": {"region": "us-central1"}},
        render_template,
    )

    assert rendered["region"] == "us-central1"
    assert rendered["api_key"][NOETL_REF_KEY]["name"] == "openai_token"
    assert rendered["api_key"][NOETL_REF_KEY]["field"] == "api_key"
    assert rendered["header"] == "Bearer {{ keychain.openai_token.api_key }}"


@pytest.mark.asyncio
async def test_resolve_credential_references_resolves_refs_and_templates(monkeypatch):
    async def fake_resolve_keychain_entries(**kwargs):
        assert kwargs["keychain_refs"] == {"openai_token"}
        return {"openai_token": {"api_key": "placeholder-secret"}}

    import noetl.worker.keychain_resolver as keychain_resolver

    monkeypatch.setattr(keychain_resolver, "resolve_keychain_entries", fake_resolve_keychain_entries)

    payload = {
        "api_key": {
            NOETL_REF_KEY: {
                "kind": "keychain",
                "name": "openai_token",
                "field": "api_key",
            }
        },
        "header": "Bearer {{ keychain.openai_token.api_key }}",
    }

    resolved, context = await resolve_credential_references(
        payload,
        {"execution_id": "2"},
        catalog_id="1",
        execution_id="2",
    )

    assert resolved == {
        "api_key": "placeholder-secret",
        "header": "Bearer placeholder-secret",
    }
    assert context["keychain"]["openai_token"]["api_key"] == "placeholder-secret"


def test_keychain_manifest_and_strip_remove_values_but_keep_hints():
    manifest = build_keychain_manifest(
        [{"name": "openai_token", "kind": "secret_manager", "map": {"api_key": "{{ path }}"}}],
        {"openai_token": {"api_key"}},
    )
    payload = {
        "keychain": {"openai_token": {"api_key": "placeholder-secret"}},
        "openai_token": {"api_key": "placeholder-secret"},
        "_keychain_manifest": manifest,
        "region": "us-central1",
    }

    stripped = strip_keychain_namespaces(payload, manifest)

    assert "keychain" not in stripped
    assert "openai_token" not in stripped
    assert stripped["_keychain_manifest"]["entries"]["openai_token"]["fields"] == ["api_key"]
    assert stripped["region"] == "us-central1"
