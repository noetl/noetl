#!/bin/bash
# Check on PyPI
# curl https://pypi.org/pypi/noetl/json
if [ -z "$1" ]; then
    echo "Usage: $0 <version>"
    echo "Example: $0 0.1.22"
    exit 1
fi

NEW_VERSION=$1
sed -i.bak "s/version = \".*\"/version = \"$NEW_VERSION\"/" pyproject.toml

rm -rf dist/ build/ *.egg-info/
./scripts/build_package.sh

uv run twine upload dist/*
git add pyproject.toml
git commit -m "Bump version to $NEW_VERSION"
git tag "v$NEW_VERSION"
git push origin main
git push origin "v$NEW_VERSION"

echo "Released version $NEW_VERSION"