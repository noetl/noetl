"""Workload form inference from a playbook / agent YAML payload.

Public entry point: ``infer_ui_schema(yaml_content) -> list[UiSchemaField]``.

Approach:
- Parse the YAML *with comments preserved* via ruamel.yaml so we can
  read `# ui:` directives next to scalar keys.
- For each top-level key under ``workload:``, build a UiSchemaField from
  the value's type plus any directives.
- Recurse for nested mappings; lists of scalars become ``kind=array``.

The inference is intentionally forgiving: if a comment is malformed or
ruamel can't load the document, we fall back to plain PyYAML and emit
a flat schema with no directives. Callers should treat the returned
schema as a best-effort hint, not a strict contract.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

import yaml as _plain_yaml

try:
    from ruamel.yaml import YAML  # type: ignore[import-not-found]

    _RUAMEL_AVAILABLE = True
except Exception:  # pragma: no cover -- ruamel always available in our deps
    _RUAMEL_AVAILABLE = False
    YAML = None  # type: ignore[assignment]

from .schema import UiSchemaField


_UI_DIRECTIVE_RE = re.compile(r"^\s*#\s*ui:(?P<key>[a-zA-Z_][a-zA-Z0-9_]*)\s*=?\s*(?P<value>.*)$")
_UI_FLAG_RE = re.compile(r"^\s*#\s*ui:(?P<key>[a-zA-Z_][a-zA-Z0-9_]*)\s*$")


def infer_ui_schema(yaml_text: str) -> list[UiSchemaField]:
    """Return ordered top-level workload fields inferred from the YAML.

    Empty list when the document has no `workload:` block.
    """
    if not yaml_text or not yaml_text.strip():
        return []

    parsed = _load_with_comments(yaml_text) or _load_plain(yaml_text)
    if parsed is None:
        return []

    workload = _get_workload(parsed)
    if workload is None:
        return []

    fields: list[UiSchemaField] = []
    for key, value in _iter_mapping_items(workload):
        directives = _read_directives(workload, key)
        fields.append(_field_from_value(str(key), value, directives))
    return fields


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _load_with_comments(yaml_text: str):
    if not _RUAMEL_AVAILABLE:
        return None
    try:
        loader = YAML(typ="rt")
        loader.preserve_quotes = True
        return loader.load(yaml_text)
    except Exception:
        return None


def _load_plain(yaml_text: str):
    try:
        return _plain_yaml.safe_load(yaml_text)
    except Exception:
        return None


def _get_workload(doc: Any) -> Optional[dict[str, Any]]:
    if not isinstance(doc, dict):
        return None
    workload = doc.get("workload")
    if not isinstance(workload, dict):
        return None
    return workload


def _iter_mapping_items(mapping: Any) -> Iterable[tuple[Any, Any]]:
    if hasattr(mapping, "items"):
        return list(mapping.items())
    return []


def _read_directives(mapping: Any, key: Any) -> dict[str, Any]:
    """Pull `# ui:foo=bar` directives from comments adjacent to a key.

    Returns a mapping of directive name -> value. Flag-style directives
    (``# ui:secret``) map to True. Returns an empty dict when ruamel is
    not in use or the key has no comments.
    """
    out: dict[str, Any] = {}
    ca = getattr(mapping, "ca", None)
    if ca is None:
        return out

    items_meta = getattr(ca, "items", None)
    if not items_meta:
        return out

    raw = items_meta.get(key)
    if not raw:
        return out

    # ruamel stores comments as a 4-tuple [pre, post, eol, multi]; the
    # exact slot depends on whether the comment is on the same line as
    # the key (eol) or above it. We inspect every slot and union them.
    for entry in raw:
        for token in _flatten_tokens(entry):
            text = getattr(token, "value", None) or str(token)
            if not text or "ui:" not in text:
                continue
            for line in text.splitlines():
                line = line.rstrip()
                if not line:
                    continue
                m = _UI_DIRECTIVE_RE.match(line)
                if m and m.group("value").strip() != "":
                    out[m.group("key")] = _parse_directive_value(m.group("value"))
                    continue
                m = _UI_FLAG_RE.match(line)
                if m:
                    out[m.group("key")] = True
    return out


def _flatten_tokens(entry: Any) -> Iterable[Any]:
    """Yield comment tokens from a ruamel comment entry, ignoring None."""
    if entry is None:
        return []
    if isinstance(entry, list):
        flat: list[Any] = []
        for sub in entry:
            flat.extend(_flatten_tokens(sub))
        return flat
    return [entry]


def _parse_directive_value(text: str) -> Any:
    text = text.strip()
    # ui:enum=[a,b,c]
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [piece.strip().strip("'\"") for piece in inner.split(",") if piece.strip()]
    # quoted
    if (text.startswith("'") and text.endswith("'")) or (
        text.startswith('"') and text.endswith('"')
    ):
        return text[1:-1]
    return text


def _field_from_value(name: str, value: Any, directives: dict[str, Any]) -> UiSchemaField:
    description = directives.get("description")
    if isinstance(description, list):
        description = ", ".join(str(part) for part in description)
    secret = bool(directives.get("secret", False))
    credential_glob = directives.get("credential")
    enum_options = directives.get("enum")

    if enum_options is not None:
        return UiSchemaField(
            name=name,
            kind="enum",
            default=value,
            description=description,
            secret=secret,
            credential_glob=credential_glob if isinstance(credential_glob, str) else None,
            options=list(enum_options) if isinstance(enum_options, (list, tuple)) else [enum_options],
        )

    if isinstance(value, bool):
        kind = "boolean"
    elif isinstance(value, int):
        kind = "integer"
    elif isinstance(value, float):
        kind = "number"
    elif value is None:
        kind = "null"
    elif isinstance(value, dict):
        children = [
            _field_from_value(str(k), v, _read_directives(value, k))
            for k, v in _iter_mapping_items(value)
        ]
        return UiSchemaField(
            name=name,
            kind="object",
            default=_clean_default(value),
            description=description,
            secret=secret,
            credential_glob=credential_glob if isinstance(credential_glob, str) else None,
            children=children,
        )
    elif isinstance(value, list):
        kind = "array"
    else:
        kind = "string"

    return UiSchemaField(
        name=name,
        kind=kind,
        default=_clean_default(value),
        description=description,
        secret=secret,
        credential_glob=credential_glob if isinstance(credential_glob, str) else None,
    )


def _clean_default(value: Any) -> Any:
    """Strip ruamel comment metadata from defaults so they JSON-serialize cleanly."""
    if isinstance(value, dict):
        return {k: _clean_default(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_default(v) for v in value]
    return value
