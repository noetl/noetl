import pytest
from jinja2 import Environment

from noetl.core.credential_refs import (
    NOETL_REF_KEY,
    build_keychain_manifest,
    encode_keychain_templates,
    is_mixed_keychain_expression,
    parse_pure_keychain_expression,
    producer_scrub_payload,
    render_preserving_keychain_refs,
    resolve_credential_references,
    scrub_arrow_ipc_bytes,
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


def test_producer_scrub_payload_redacts_headers_and_keychain_namespaces():
    payload = {
        "headers": {
            "Authorization": "Bearer placeholder-token",
            "X-API-Key": "placeholder-token",
            "Cookie": "session=placeholder-token",
        },
        "body": {"ok": True},
        "keychain": {"openai_token": {"api_key": "placeholder-secret"}},
    }

    scrubbed = producer_scrub_payload(payload)

    assert scrubbed["headers"]["Authorization"] == "[REDACTED]"
    assert scrubbed["headers"]["X-API-Key"] == "[REDACTED]"
    assert scrubbed["headers"]["Cookie"] == "[REDACTED]"
    assert scrubbed["body"] == {"ok": True}
    assert "keychain" not in scrubbed


def test_producer_scrub_payload_uses_context_secret_values():
    payload = {"value": "prefix placeholder-secret suffix"}
    context = {"keychain": {"openai_token": {"api_key": "placeholder-secret"}}}

    scrubbed = producer_scrub_payload(payload, context)

    assert scrubbed["value"] == "[REDACTED]"


def test_scrub_arrow_ipc_bytes_redacts_valid_rows():
    from noetl.core.storage.arrow_ipc import arrow_ipc_to_rows, rows_to_arrow_ipc

    payload, schema_digest, row_count = rows_to_arrow_ipc(
        [{"id": 1, "Authorization": "Bearer placeholder-token"}]
    )

    safe_payload, safe_schema_digest, safe_row_count, scrubbed = scrub_arrow_ipc_bytes(
        payload,
        schema_digest=schema_digest,
        row_count=row_count,
    )

    assert scrubbed is True
    assert safe_schema_digest
    assert safe_row_count == 1
    assert arrow_ipc_to_rows(safe_payload) == [{"id": 1, "Authorization": "[REDACTED]"}]
