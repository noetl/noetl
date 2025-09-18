#!/usr/bin/env python3
"""
Validate NoETL playbooks for the standardized iterator + metadata schema.

Checks (fails on any violation):
  - File parses as YAML with kind: Playbook
  - metadata.name and metadata.path are present
  - No legacy loop constructs (type: loop, loop:, in:/iterator: at step level)
  - For type: iterator steps, both collection and element are present

Usage:
  python scripts/validate_playbooks.py [ROOT_DIR]

Defaults to scanning ./examples when ROOT_DIR not provided.
Exits with code 1 on any violation; prints a summary report.
"""

from __future__ import annotations

import sys
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    import yaml  # type: ignore
except Exception as e:
    print("ERROR: PyYAML is required to run validator (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)


def iter_playbook_files(root: Path) -> List[Path]:
    files: List[Path] = []
    for p in root.rglob("*.yaml"):
        # Skip credential payloads folder
        if "credentials" in p.parts:
            continue
        files.append(p)
    for p in root.rglob("*.yml"):
        if "credentials" in p.parts:
            continue
        files.append(p)
    # De-duplicate
    return sorted(set(files))


def load_yaml(path: Path) -> Dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None


def validate_playbook(doc: Dict[str, Any]) -> List[str]:
    errs: List[str] = []

    if str(doc.get("kind", "")).strip() != "Playbook":
        # Not a playbook; ignore silently
        return errs

    md = doc.get("metadata") or {}
    if not isinstance(md, dict):
        md = {}
    md_name = md.get("name")
    md_path = md.get("path")
    if not md_name or not md_path:
        errs.append("missing metadata.name or metadata.path")

    # Check iterator usage and legacy loop constructs
    workflow = doc.get("workflow") or []
    if not isinstance(workflow, list):
        return errs

    for step in workflow:
        if not isinstance(step, dict):
            continue
        st_name = step.get("step") or step.get("name") or "<unnamed>"
        t = str(step.get("type") or "").strip().lower()

        # Legacy markers
        if t == "loop":
            errs.append(f"step '{st_name}': legacy type: loop is not allowed (use type: iterator)")
        if isinstance(step.get("loop"), dict):
            errs.append(f"step '{st_name}': legacy 'loop:' block is not allowed (use type: iterator)")
        # Common legacy fields at step-level
        if "in" in step or "iterator" in step or "elements" in step or "index" in step or "for_each" in step or "each" in step or "map" in step:
            errs.append(f"step '{st_name}': legacy iteration keys present (use collection/element under type: iterator)")

        if t == "iterator":
            coll = step.get("collection")
            elem = step.get("element")
            if coll is None or elem is None:
                errs.append(f"step '{st_name}': iterator requires both 'collection' and 'element'")

    return errs


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("examples")
    files = iter_playbook_files(root)
    problems: List[Tuple[str, List[str]]] = []
    for fp in files:
        doc = load_yaml(fp)
        if not isinstance(doc, dict):
            # Not a playbook YAML or invalid YAML
            continue
        if str(doc.get("kind", "")).strip() != "Playbook":
            continue
        errs = validate_playbook(doc)
        if errs:
            problems.append((str(fp), errs))

    if problems:
        print("Playbook validation failed:\n")
        for path, errs in problems:
            print(f"- {path}")
            for e in errs:
                print(f"  * {e}")
        print(f"\nTotal invalid playbooks: {len(problems)}")
        return 1
    else:
        print(f"OK: All playbooks under {root} pass iterator+metadata validation ({len(files)} files scanned).")
        return 0


if __name__ == "__main__":
    sys.exit(main())

