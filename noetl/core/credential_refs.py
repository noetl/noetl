"""Credential reference helpers for storage-safe keychain handling."""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from jinja2 import BaseLoader, Environment

from noetl.core.sanitize import REDACTED, redact_keychain_values

NOETL_REF_KEY = "$noetl_ref"
KEYCHAIN_REF_KIND = "keychain"
KEYCHAIN_MANIFEST_KEY = "_keychain_manifest"
HEADER_CREDENTIAL_KEYS = {
    "authorization",
    "proxy_authorization",
    "www_authenticate",
    "x_api_key",
    "x_auth_token",
    "x_access_token",
    "cookie",
    "set_cookie",
}

_JINJA_EXPR_RE = re.compile(r"^\s*\{\{\s*(.*?)\s*\}\}\s*$", re.DOTALL)
_KEYCHAIN_DOT_RE = re.compile(
    r"^keychain\.([A-Za-z_][A-Za-z0-9_-]*)(?:\.([A-Za-z_][A-Za-z0-9_-]*))?\s*$"
)
_KEYCHAIN_BRACKET_RE = re.compile(
    r"^keychain\[['\"]([^'\"]+)['\"]\](?:\[['\"]([^'\"]+)['\"]\])?\s*$"
)
_KEYCHAIN_SEARCH_RE = re.compile(
    r"keychain(?:\.([A-Za-z_][A-Za-z0-9_-]*)|\[['\"]([^'\"]+)['\"]\])"
)


def keychain_ref(name: str, field: Optional[str] = None) -> dict[str, Any]:
    return {
        NOETL_REF_KEY: {
            "kind": KEYCHAIN_REF_KIND,
            "name": name,
            "field": field,
        }
    }


def is_keychain_ref(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    ref = value.get(NOETL_REF_KEY)
    return isinstance(ref, dict) and ref.get("kind") == KEYCHAIN_REF_KIND and bool(ref.get("name"))


def build_keychain_manifest(keychain_section: Any, resolved_fields: Optional[dict[str, set[str]]] = None) -> dict[str, Any]:
    entries: dict[str, dict[str, Any]] = {}
    if not isinstance(keychain_section, list):
        return {"entries": entries}

    for entry in keychain_section:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        fields: set[str] = set()
        map_config = entry.get("map")
        if isinstance(map_config, dict):
            fields.update(str(k) for k in map_config.keys())
        if isinstance(resolved_fields, dict):
            fields.update(str(k) for k in resolved_fields.get(str(name), set()))
        entries[str(name)] = {
            "kind": entry.get("kind") or entry.get("type") or "unknown",
            "fields": sorted(fields),
        }
    return {"entries": entries}


def keychain_names_from_manifest(manifest: Any) -> set[str]:
    if not isinstance(manifest, dict):
        return set()
    entries = manifest.get("entries")
    if not isinstance(entries, dict):
        return set()
    return {str(name) for name in entries.keys()}


def parse_pure_keychain_expression(template: str) -> Optional[dict[str, Any]]:
    if not isinstance(template, str):
        return None

    match = _JINJA_EXPR_RE.match(template)
    if not match:
        return None

    inner = match.group(1).strip()
    base = inner.split("|", 1)[0].strip()
    dot_match = _KEYCHAIN_DOT_RE.match(base)
    if dot_match:
        return keychain_ref(dot_match.group(1), dot_match.group(2))

    bracket_match = _KEYCHAIN_BRACKET_RE.match(base)
    if bracket_match:
        return keychain_ref(bracket_match.group(1), bracket_match.group(2))

    return None


def contains_keychain_template(value: Any) -> bool:
    return isinstance(value, str) and "{{" in value and "}}" in value and "keychain" in value and bool(_KEYCHAIN_SEARCH_RE.search(value))


def is_mixed_keychain_expression(value: Any) -> bool:
    if not contains_keychain_template(value):
        return False
    return parse_pure_keychain_expression(value) is None


def encode_keychain_templates(value: Any) -> Any:
    if isinstance(value, str):
        parsed = parse_pure_keychain_expression(value)
        return parsed if parsed is not None else value
    if isinstance(value, dict):
        return {k: encode_keychain_templates(v) for k, v in value.items()}
    if isinstance(value, list):
        return [encode_keychain_templates(item) for item in value]
    if isinstance(value, tuple):
        return tuple(encode_keychain_templates(item) for item in value)
    return value


def render_preserving_keychain_refs(
    env: Environment,
    value: Any,
    context: dict[str, Any],
    render_fn: Callable[[Environment, Any, dict[str, Any]], Any],
) -> Any:
    if isinstance(value, str):
        parsed = parse_pure_keychain_expression(value)
        if parsed is not None:
            return parsed
        if is_mixed_keychain_expression(value):
            return value
        return render_fn(env, value, context)
    if isinstance(value, dict):
        return {k: render_preserving_keychain_refs(env, v, context, render_fn) for k, v in value.items()}
    if isinstance(value, list):
        return [render_preserving_keychain_refs(env, item, context, render_fn) for item in value]
    if isinstance(value, tuple):
        return tuple(render_preserving_keychain_refs(env, item, context, render_fn) for item in value)
    return value


def extract_keychain_ref_names(value: Any) -> set[str]:
    refs: set[str] = set()
    if is_keychain_ref(value):
        refs.add(str(value[NOETL_REF_KEY]["name"]))
        return refs
    if isinstance(value, dict):
        for item in value.values():
            refs.update(extract_keychain_ref_names(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            refs.update(extract_keychain_ref_names(item))
    elif isinstance(value, str) and contains_keychain_template(value):
        refs.update(match.group(1) or match.group(2) for match in _KEYCHAIN_SEARCH_RE.finditer(value))
    return {ref for ref in refs if ref}


def strip_keychain_namespaces(value: Any, manifest: Any = None) -> Any:
    blocked = {"keychain"}
    blocked.update(keychain_names_from_manifest(manifest))
    return _strip_keychain_namespaces(value, blocked)


def producer_scrub_payload(
    value: Any,
    context: Optional[dict[str, Any]] = None,
    *,
    additional_keys: Optional[set[str]] = None,
    secret_values: Optional[set[str]] = None,
    redaction: str = REDACTED,
) -> Any:
    """Return a storage-safe copy for producer-side result/temp writes."""
    context = context or {}
    manifest = context.get(KEYCHAIN_MANIFEST_KEY) if isinstance(context, dict) else None
    keys = set(HEADER_CREDENTIAL_KEYS)
    if additional_keys:
        keys.update(str(key).lower().replace("-", "_") for key in additional_keys)

    if isinstance(manifest, dict):
        entries = manifest.get("entries")
        if isinstance(entries, dict):
            keys.update(str(name).lower().replace("-", "_") for name in entries.keys())
            for entry in entries.values():
                if isinstance(entry, dict) and isinstance(entry.get("fields"), list):
                    keys.update(str(field).lower().replace("-", "_") for field in entry["fields"])

    values = set(secret_values or set())
    if isinstance(context, dict):
        values.update(_collect_secret_strings(context.get("keychain")))

    stripped = strip_keychain_namespaces(value, manifest)
    return redact_keychain_values(
        stripped,
        additional_keys=keys,
        secret_values=values,
        redaction=redaction,
    )


def scrub_arrow_ipc_bytes(
    data_bytes: bytes,
    *,
    schema_digest: str,
    row_count: Optional[int] = None,
    context: Optional[dict[str, Any]] = None,
) -> tuple[bytes, str, Optional[int], bool]:
    """Scrub valid Arrow IPC row payloads before durable or IPC-cache writes."""
    try:
        from noetl.core.storage.arrow_ipc import arrow_ipc_to_rows, rows_to_arrow_ipc

        rows = arrow_ipc_to_rows(bytes(data_bytes))
    except Exception:
        return bytes(data_bytes), schema_digest, row_count, False

    safe_rows = producer_scrub_payload(rows, context)
    if safe_rows == rows:
        return bytes(data_bytes), schema_digest, row_count if row_count is not None else len(rows), False

    payload, safe_schema_digest, safe_row_count = rows_to_arrow_ipc(safe_rows)
    return payload, safe_schema_digest, safe_row_count, True


def _collect_secret_strings(value: Any) -> set[str]:
    values: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            values.update(_collect_secret_strings(item))
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            values.update(_collect_secret_strings(item))
    elif isinstance(value, str) and value:
        values.add(value)
    return values


def _strip_keychain_namespaces(value: Any, blocked: set[str]) -> Any:
    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            if str(k) == KEYCHAIN_MANIFEST_KEY:
                result[k] = v
                continue
            if str(k) in blocked:
                continue
            result[k] = _strip_keychain_namespaces(v, blocked)
        return result
    if isinstance(value, list):
        return [_strip_keychain_namespaces(item, blocked) for item in value]
    if isinstance(value, tuple):
        return tuple(_strip_keychain_namespaces(item, blocked) for item in value)
    return value


async def resolve_credential_references(
    value: Any,
    context: dict[str, Any],
    *,
    catalog_id: int | str,
    execution_id: Optional[int | str] = None,
    api_base_url: str = "http://noetl.noetl.svc.cluster.local:8082",
    refresh_threshold_seconds: int = 300,
) -> tuple[Any, dict[str, Any]]:
    names = extract_keychain_ref_names(value)
    resolved_keychain: dict[str, Any] = {}
    if names:
        from noetl.worker.keychain_resolver import resolve_keychain_entries

        resolved_keychain = await resolve_keychain_entries(
            keychain_refs=names,
            catalog_id=int(catalog_id),
            execution_id=int(execution_id) if execution_id is not None else None,
            api_base_url=api_base_url,
            refresh_threshold_seconds=refresh_threshold_seconds,
        )

    resolved_context = dict(context or {})
    if resolved_keychain:
        resolved_context["keychain"] = resolved_keychain

    env = Environment(loader=BaseLoader())
    from noetl.core.dsl.render import add_b64encode_filter, render_template

    env = add_b64encode_filter(env)
    return _resolve_value(value, resolved_context, env, render_template), resolved_context


def _resolve_value(value: Any, context: dict[str, Any], env: Environment, render_fn: Callable[..., Any]) -> Any:
    if is_keychain_ref(value):
        ref = value[NOETL_REF_KEY]
        data = context.get("keychain", {}).get(ref.get("name"), {})
        field = ref.get("field")
        if field is None:
            return data
        if isinstance(data, dict):
            return data.get(field)
        return None
    if isinstance(value, str) and contains_keychain_template(value):
        return render_fn(env, value, context)
    if isinstance(value, dict):
        return {k: _resolve_value(v, context, env, render_fn) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_value(item, context, env, render_fn) for item in value]
    if isinstance(value, tuple):
        return tuple(_resolve_value(item, context, env, render_fn) for item in value)
    return value
