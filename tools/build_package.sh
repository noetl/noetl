#!/usr/bin/env bash
# Build the NoETL Python package into dist/
#
# Usage:
#   tools/build_package.sh
#
# This script cleans dist/ and runs `python -m build`.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "[build_package] Cleaning dist/"
rm -rf dist
mkdir -p dist

# Ensure build tools are present (works with uv or regular python)
if command -v uv >/dev/null 2>&1; then
  echo "[build_package] Installing build dependencies via uv (dev)"
  uv add --dev build twine >/dev/null 2>&1 || true
fi

echo "[build_package] Building package"
python -m build

echo "[build_package] Done. Artifacts in dist/"
