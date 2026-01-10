#!/bin/bash
set -e

VERSION=${1:-2.5.3}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "🐳 Building Debian package in Docker..."
echo "Version: $VERSION"

cd "$REPO_ROOT"

# Build Docker image for building .deb
docker build \
  -f docker/release/Dockerfile.deb \
  -t noetl-deb-builder:${VERSION} \
  --build-arg VERSION=${VERSION} \
  .

# Extract .deb from container
echo "📦 Extracting .deb package..."
CONTAINER_ID=$(docker create noetl-deb-builder:${VERSION})
docker cp ${CONTAINER_ID}:/build/build/deb/. build/deb/
docker rm ${CONTAINER_ID}

echo ""
echo "✅ Debian package built successfully!"
ls -lh build/deb/
echo ""
echo "Test installation:"
echo "  docker run --rm -v \$(pwd)/build/deb:/packages ubuntu:22.04 bash -c 'apt-get update && dpkg -i /packages/noetl_${VERSION}-1_*.deb || apt-get install -f -y'"
