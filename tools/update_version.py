#!/usr/bin/env python3
"""
Update version in pyproject.toml

Usage:
  python tools/update_version.py [major|minor|patch|<version>]

Examples:
  python tools/update_version.py patch
  python tools/update_version.py minor
  python tools/update_version.py 1.0.0

This script updates the [project].version field in pyproject.toml.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def parse_version(v: str) -> tuple[int, int, int]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", v)
    if not m:
        raise ValueError(f"Invalid version: {v}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def bump(kind: str, v: str) -> str:
    major, minor, patch = parse_version(v)
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    if kind == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"Unknown bump kind: {kind}")


def read_current_version(pyproject: Path) -> str:
    content = pyproject.read_text(encoding="utf-8")
    m = re.search(r"^version\s*=\s*['\"]([^'\"]+)['\"]\s*$", content, re.MULTILINE)
    if not m:
        # try within [project] block broadly
        m = re.search(r"version\s*=\s*['\"]([^'\"]+)['\"]", content)
    if not m:
        raise RuntimeError("Could not find version in pyproject.toml")
    return m.group(1)


def write_version(pyproject: Path, new_version: str) -> None:
    content = pyproject.read_text(encoding="utf-8")
    content_new = re.sub(
        r"(version\s*=\s*['\"])([^'\"]+)(['\"])",
        rf"\g<1>{new_version}\3",
        content,
        count=1,
    )
    if content == content_new:
        raise RuntimeError("Failed to update version in pyproject.toml")
    pyproject.write_text(content_new, encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: python tools/update_version.py [major|minor|patch|<version>]")
        return 1

    arg = argv[1].strip()
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    if not pyproject.exists():
        print("pyproject.toml not found")
        return 2

    current = read_current_version(pyproject)

    if arg in {"major", "minor", "patch"}:
        new_version = bump(arg, current)
    else:
        # explicit version
        # allow v prefix, strip it
        if arg.startswith("v"):
            arg = arg[1:]
        # validate
        _ = parse_version(arg)
        new_version = arg

    write_version(pyproject, new_version)
    print(f"Updated version: {current} -> {new_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
