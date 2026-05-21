#!/usr/bin/env python
"""Build a Phase 5 storage backend registry evidence report."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from noetl.core.storage import registered_backend_names

BACKEND_CONSTRUCTION_RE = re.compile(r"\b(NATSKVBackend|DiskCacheBackend|S3Backend|GCSBackend)\s*\(")
CONSUMER_PATTERNS = {
    "result_store": ("noetl/core/storage/result_store.py", "get_backend("),
    "artifact_executor": ("noetl/tools/artifact/executor.py", "get_backend(\"kv\""),
    "agent_disk_fallback": ("noetl/tools/agent/executor.py", "get_backend(\"disk\""),
}
DIRECT_CONSTRUCTION_IGNORES = {
    "noetl/core/storage/backends.py",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _consumer_paths(repo_root: Path) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for name, (relative_path, needle) in CONSUMER_PATTERNS.items():
        path = repo_root / relative_path
        try:
            results[name] = needle in _read(path)
        except OSError:
            results[name] = False
    return results


def _direct_backend_construction(repo_root: Path) -> dict[str, Any]:
    unexpected: list[dict[str, Any]] = []
    for path in sorted((repo_root / "noetl").rglob("*.py")):
        relative_path = path.relative_to(repo_root).as_posix()
        if relative_path in DIRECT_CONSTRUCTION_IGNORES:
            continue
        try:
            lines = _read(path).splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if BACKEND_CONSTRUCTION_RE.search(line):
                unexpected.append(
                    {
                        "path": relative_path,
                        "line": line_number,
                        "text": line.strip(),
                    }
                )
    return {
        "matched": not unexpected,
        "unexpected": unexpected,
    }


def build_storage_phase5_report(repo_root: Path) -> dict[str, Any]:
    """Return a deterministic storage registry evidence report."""
    root = repo_root.resolve()
    return {
        "registered_backends": list(registered_backend_names()),
        "consumer_paths": _consumer_paths(root),
        "direct_backend_construction": _direct_backend_construction(root),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a Phase 5 storage registry evidence report")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    report = build_storage_phase5_report(args.repo_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"matched": True, "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
