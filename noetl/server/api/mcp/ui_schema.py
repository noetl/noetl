"""Workload form inference from a playbook / agent YAML payload.

Public entry point: ``infer_ui_schema(yaml_content) -> list[UiSchemaField]``.

Approach:

- Parse the document with plain PyYAML for the structural shape (no
  extra dependency on ruamel).
- Scan the raw text for inline ``# ui:`` directives next to the line
  that defines each workload key. The directive parser is a small
  regex; it ignores anything it can't recognise so a malformed
  comment never breaks registration.

Supported directives (always after the key/value on the same line):

- ``# ui:secret`` -- mark the field as masked input.
- ``# ui:enum=[a,b,c]`` -- force ``kind=enum`` and populate options.
- ``# ui:credential=pg_*`` -- restrict to a credential picker
  filtered by glob.
- ``# ui:description=Some help text`` -- per-field description.

The inference is intentionally forgiving: malformed YAML or unknown
directives just return an empty / less-rich schema rather than
raising. Callers should treat the returned schema as a best-effort
hint, not a strict contract.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

import yaml as _yaml

from .schema import UiSchemaField


# Match each `# ui:foo[=bar]` token within a line. We use ``finditer``
# instead of an end-anchored match so two directives on one line both
# get parsed (e.g. ``# ui:secret # ui:description=API key``). The
# value capture stops at whitespace-then-``#`` so it doesn't swallow a
# trailing directive.
_DIRECTIVE_INLINE_RE = re.compile(
    r"#\s*ui:(?P<key>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s*=\s*(?P<value>[^\n#]*?))?(?=(?:\s+#|\s*$))"
)

# Match the start of a top-level workload key line so we can correlate
# the parsed dict back to the raw text. We accept any indent of two or
# more spaces so this works for the common 2-space indent and the
# also-valid 4-space style.
_TOP_KEY_RE = re.compile(r"^(?P<indent> {2,})(?P<name>[A-Za-z_][A-Za-z0-9_-]*)\s*:")


def infer_ui_schema(yaml_text: str) -> list[UiSchemaField]:
    """Return ordered top-level workload fields inferred from the YAML.

    Empty list when the document has no `workload:` block.
    """
    if not yaml_text or not yaml_text.strip():
        return []

    parsed = _load_yaml(yaml_text)
    workload = _get_workload(parsed)
    if workload is None:
        return []

    directives = _scan_inline_directives(yaml_text)
    fields: list[UiSchemaField] = []
    for key, value in workload.items():
        fields.append(
            _field_from_value(str(key), value, directives.get(str(key), {}))
        )
    return fields


# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------


def _load_yaml(yaml_text: str) -> Any:
    try:
        return _yaml.safe_load(yaml_text)
    except Exception:
        return None


def _get_workload(doc: Any) -> Optional[dict[str, Any]]:
    if not isinstance(doc, dict):
        return None
    workload = doc.get("workload")
    if not isinstance(workload, dict):
        return None
    return workload


# ---------------------------------------------------------------------------
# Comment scanning
# ---------------------------------------------------------------------------


def _scan_inline_directives(yaml_text: str) -> dict[str, dict[str, Any]]:
    """Walk the raw text once and pull `# ui:` directives per top-level key.

    Returns a mapping of ``key_name -> directive_dict`` where the
    directive dict has entries like ``{"secret": True, "enum":
    ["a", "b"], "description": "...", "credential": "pg_*"}``.

    Only inline comments on the same line as the key/value are
    considered. The implementation deliberately ignores keys nested
    deeper than the immediate workload children — Phase 1 covers the
    flat case the GUI run-dialog needs first.
    """
    out: dict[str, dict[str, Any]] = {}
    in_workload = False
    workload_indent = -1

    for line in yaml_text.splitlines():
        stripped = line.lstrip()
        if not stripped:
            continue
        if stripped.startswith("workload:"):
            in_workload = True
            workload_indent = len(line) - len(stripped)
            continue
        if not in_workload:
            continue

        indent = len(line) - len(stripped)
        if stripped and indent <= workload_indent and not line.startswith(" "):
            # Left the workload block.
            in_workload = False
            continue

        match = _TOP_KEY_RE.match(line)
        if not match:
            continue
        key_name = match.group("name")
        directives = _extract_directives_from_line(line)
        if directives:
            out[key_name] = directives

    return out


def _extract_directives_from_line(line: str) -> dict[str, Any]:
    """Pull every ``# ui:foo`` / ``# ui:foo=bar`` token from one raw line.

    Uses :func:`re.finditer` so multiple directives on a single line are
    parsed independently — each match is anchored only at the start of
    a directive and the value capture is non-greedy with a lookahead
    that terminates on the next ``# ui:`` token or end of line.
    """
    out: dict[str, Any] = {}
    for match in _DIRECTIVE_INLINE_RE.finditer(line):
        key = match.group("key")
        raw_value = (match.group("value") or "").strip()
        out[key] = _parse_directive_value(raw_value) if raw_value else True
    return out


def _parse_directive_value(text: str) -> Any:
    text = text.strip()
    # ui:enum=[a,b,c]
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [piece.strip().strip("'\"") for piece in inner.split(",") if piece.strip()]
    # quoted single value
    if (text.startswith("'") and text.endswith("'")) or (
        text.startswith('"') and text.endswith('"')
    ):
        return text[1:-1]
    return text


# ---------------------------------------------------------------------------
# Field construction
# ---------------------------------------------------------------------------


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
            _field_from_value(str(k), v, {})
            for k, v in value.items()
        ]
        return UiSchemaField(
            name=name,
            kind="object",
            default=value,
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
        default=value,
        description=description,
        secret=secret,
        credential_glob=credential_glob if isinstance(credential_glob, str) else None,
    )
