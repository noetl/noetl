#!/bin/bash
set -euo pipefail

if [ -z "${1:-}" ]; then
  echo "Usage: $0 <version>"
  echo "Example: $0 0.1.40"
  exit 1
fi

NEW_VERSION="$1"
SEMVER_REGEX='^[0-9]+\.[0-9]+\.[0-9]+(\-[A-Za-z0-9\.]+)?(\+[A-Za-z0-9\.]+)?$'
if ! [[ "$NEW_VERSION" =~ $SEMVER_REGEX ]]; then
  echo "Error: version '$NEW_VERSION' is not a valid semver (e.g., 0.1.40)" >&2
  exit 1
fi

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO_ROOT"

CURRENT_VERSION=$(grep -E '^version\s*=\s*"[^"]+"' pyproject.toml | sed -E 's/^version\s*=\s*"([^"]+)"/\1/') || true
if [ -z "${CURRENT_VERSION:-}" ]; then
  echo "Could not detect current version from pyproject.toml" >&2
  exit 1
fi

echo "Current version: $CURRENT_VERSION"
echo "New version:     $NEW_VERSION"

read -p "Proceed to update all references and publish? (y/N): " RESP
if [[ "${RESP:-}" != "y" && "${RESP:-}" != "Y" && "${RESP:-}" != "yes" ]]; then
  echo "Aborted."
  exit 0
fi

if command -v python3 >/dev/null 2>&1; then
  python3 scripts/update_version.py "$NEW_VERSION" || { echo "update_version.py failed" >&2; exit 1; }
else
  echo "python3 not found; attempting direct pyproject.toml update" >&2
  sed -i.bak "s/^version = \".*\"/version = \"$NEW_VERSION\"/" pyproject.toml
fi

if grep -qE '^VERSION="[^"]*"' Makefile; then
  sed -i.bak "s/^VERSION=\"[^\"]*\"/VERSION=\"$NEW_VERSION\"/" Makefile
fi

shopt -s nullglob
DOC_FILES=(README.md docs/*.md docs/**/*.md)
for f in "${DOC_FILES[@]}"; do
  if [ -f "$f" ]; then
    sed -i.bak -E "s/(noetl==)${CURRENT_VERSION//./\\.}/\\1$NEW_VERSION/g" "$f" || true
  fi
done

SEARCH_GLOBS=(k8s/**/*.yaml k8s/**/*.yml k8s/*.yaml k8s/*.yml docker/**/*.yaml docker/**/*.yml docker/**/Dockerfile docker/*.yaml docker/*.yml)
for g in "${SEARCH_GLOBS[@]}"; do
  for f in $g; do
    [ -f "$f" ] || continue
    sed -i.bak -E "s#(noetl/(noetl)?[:@]?)${CURRENT_VERSION//./\\.}#\\1$NEW_VERSION#g" "$f" || true
    sed -i.bak -E "s#(ghcr\\.io/noetl/noetl:)${CURRENT_VERSION//./\\.}#\\1$NEW_VERSION#g" "$f" || true
  done
done

find . -type f -name "*.bak" -delete || true

./scripts/build_ui.sh

rm -rf dist/ build/ *.egg-info/
./scripts/build_package.sh

if command -v uv >/dev/null 2>&1; then
  uv run twine upload dist/*
else
  twine upload dist/*
fi

git add pyproject.toml noetl/__init__.py CHANGELOG.md Makefile || true
git add docs/ k8s/ docker/ noetl/ui/ || true

git commit -m "Release v$NEW_VERSION: update version references"
git tag "v$NEW_VERSION"
git push origin main
git push origin "v$NEW_VERSION"

echo "Released version $NEW_VERSION"
