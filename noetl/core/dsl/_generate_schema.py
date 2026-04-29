"""Regenerate noetl/core/dsl/playbook.schema.json from the v10 Pydantic models.

The previous hand-maintained schemas (``playbook_schema.json`` +
``playbook_normalized_schema.json``) drifted badly out of sync with the
runtime models — they predate v10 entirely (no ``NextRouter``, no
``tool: { kind: ... }``, no ``executor`` block) and were never wired
into any code path, so the drift went unnoticed until a Pydantic
``ValidationError`` surfaced as ``"Playbook not found: catalog_id=..."``
at execute time.

This script generates a single canonical JSON Schema directly from the
authoritative Pydantic models. Run it whenever the v10 models change
and commit the resulting JSON alongside the model edit.

Usage::

    cd repos/noetl
    python -m noetl.core.dsl._generate_schema

The output goes to ``noetl/core/dsl/playbook.schema.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

from noetl.core.dsl.engine.models.executor import Playbook


SCHEMA_ID = "https://noetl.io/schemas/playbook.json"
SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_TITLE = "NoETL Playbook (canonical v10)"
SCHEMA_DESCRIPTION = (
    "JSON Schema for NoETL v10 playbooks. Auto-generated from "
    "noetl.core.dsl.engine.models.executor.Playbook via "
    "Playbook.model_json_schema(); regenerate with "
    "`python -m noetl.core.dsl._generate_schema` whenever the "
    "Pydantic models change."
)

OUT_PATH = Path(__file__).parent / "playbook.schema.json"


def _build_schema() -> dict:
    schema = Playbook.model_json_schema()

    # Pydantic emits a JSON Schema Draft 2020-12-compatible document but
    # without a ``$schema`` declaration. Adding one helps editors that
    # auto-validate YAML against the URI in `$id` (VS Code, IntelliJ,
    # nvim w/ jsonls).
    schema["$schema"] = SCHEMA_DRAFT
    schema["$id"] = SCHEMA_ID
    schema.setdefault("title", SCHEMA_TITLE)
    schema["description"] = SCHEMA_DESCRIPTION
    return schema


def main() -> None:
    schema = _build_schema()
    OUT_PATH.write_text(json.dumps(schema, indent=2, sort_keys=False) + "\n")
    print(f"wrote {OUT_PATH} ({OUT_PATH.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
