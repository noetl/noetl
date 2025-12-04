#!/usr/bin/env python3
"""
Codemod: migrate legacy loop constructs to the unified iterator schema.

Usage:
  - Dry run (prints planned changes):
      python3 scripts/migrate_loops_to_iterator.py --dry-run
  - Apply in place:
      python3 scripts/migrate_loops_to_iterator.py --apply

Targets (recursive):
  workflows/, data/, playbooks/, tests/fixtures/playbooks/

Transforms:
  - type: loop          -> type: iterator
  - in                  -> collection
  - iterator            -> element
  - mode: parallel      -> mode: async
  - until               -> where (best-effort, only when a simple predicate)
  - loop: { in, iterator, ... } -> hoisted to top-level iterator fields

Guardrails:
  - Preserve comments and ordering (ruamel.yaml)
  - Do not change Jinja internals
  - If both 'task' and 'run' present, leave unchanged and add a TODO comment
  - If a 'loop:' block is found without obvious 'task' or 'run', leave a TODO
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Tuple

try:
    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap
except Exception:
    YAML = None  # type: ignore


ROOTS = ["workflows", "data", "playbooks", "tests/fixtures/playbooks"]
GLOBS = ["**/*.yaml", "**/*.yml"]


def is_simple_predicate(val: Any) -> bool:
    # Heuristic: allow plain strings (including Jinja), bools
    return isinstance(val, (str, bool))


def transform_mapping(node: CommentedMap, file_path: Path) -> Tuple[bool, list[str]]:
    changed = False
    notes: list[str] = []

    # 1) Hoist loop block
    if isinstance(node.get("loop"), dict):
        loop = node["loop"]
        node.pop("loop", None)
        # Set type
        node["type"] = "iterator"
        # Move fields
        if "in" in loop and "collection" not in node:
            node["collection"] = loop.get("in")
        if "iterator" in loop and "element" not in node:
            node["element"] = loop.get("iterator")
        if "mode" in loop and "mode" not in node:
            node["mode"] = "async" if str(loop.get("mode")).strip().lower() == "parallel" else loop.get("mode")
        if "until" in loop:
            if is_simple_predicate(loop.get("until")) and "where" not in node:
                node["where"] = loop.get("until")
            else:
                notes.append("# TODO(migration): 'until' not auto-translated; please review")
        changed = True

    # 2) Direct field renames at this level
    t = node.get("type")
    if isinstance(t, str) and t.strip().lower() == "loop":
        node["type"] = "iterator"
        changed = True

    if "in" in node and "collection" not in node:
        node["collection"] = node.pop("in")
        changed = True

    if "iterator" in node and "element" not in node:
        node["element"] = node.pop("iterator")
        changed = True

    mode = node.get("mode")
    if isinstance(mode, str) and mode.strip().lower() == "parallel":
        node["mode"] = "async"
        changed = True

    if "until" in node:
        if is_simple_predicate(node.get("until")) and "where" not in node:
            node["where"] = node.pop("until")
        else:
            # Keep original and add a TODO comment line
            notes.append("# TODO(migration): 'until' not auto-translated; please move semantics to 'where:' if purely a predicate")
            # Do not remove original to avoid breaking behavior
        changed = True

    # 3) Detect ambiguous run/task bodies
    if "task" in node and "run" in node:
        notes.append("# TODO(migration): both 'task' and 'run' present; migration requires exactly one. Please split or consolidate.")

    return changed, notes


def walk(node: Any, file_path: Path) -> Tuple[bool, list[str]]:
    changed = False
    notes: list[str] = []
    if isinstance(node, CommentedMap):
        ch, ns = transform_mapping(node, file_path)
        if ch:
            changed = True
            notes.extend(ns)
        for k, v in list(node.items()):
            ch2, ns2 = walk(v, file_path)
            if ch2:
                changed = True
                notes.extend(ns2)
    elif isinstance(node, list):
        for item in node:
            ch3, ns3 = walk(item, file_path)
            if ch3:
                changed = True
                notes.extend(ns3)
    return changed, notes


def process_file(path: Path, apply: bool) -> Tuple[bool, str]:
    if YAML is None:
        return False, "ruamel.yaml not installed; cannot run migration script"
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=2, offset=2)

    try:
        data = yaml.load(path.read_text(encoding="utf-8"))
    except Exception as e:
        return False, f"Failed to parse {path}: {e}"

    changed, notes = walk(data, path)
    if not changed and not notes:
        return False, f"No changes for {path}"

    if apply:
        # Append notes as a leading comment at file head if present
        if notes:
            head = "\n".join(notes) + "\n"
            existing = path.read_text(encoding="utf-8")
            path.write_text(head + existing, encoding="utf-8")
        with path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f)
        return True, f"Updated {path}"
    else:
        return True, f"Would update {path}{' with notes' if notes else ''}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Apply changes in-place")
    ap.add_argument("--dry-run", action="store_true", help="Print planned changes only")
    args = ap.parse_args()
    apply = bool(args.apply and not args.dry_run)

    any_changed = False
    for root in ROOTS:
        p = Path(root)
        if not p.exists():
            continue
        for g in GLOBS:
            for fp in p.glob(g):
                changed, msg = process_file(fp, apply)
                if changed:
                    any_changed = True
                print(msg)
    if not any_changed:
        print("No files required migration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

