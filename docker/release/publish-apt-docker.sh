#!/bin/bash
set -e

VERSION=${1:-2.5.4}
ARCH=${2:-arm64}
DEB_FILE="build/deb/noetl_${VERSION}-1_${ARCH}.deb"

if [ ! -f "$DEB_FILE" ]; then
    echo "❌ Package not found: $DEB_FILE"
    echo "Build it first with: ./docker/release/build-deb-docker.sh $VERSION"
    exit 1
fi

echo "📦 Publishing NoETL .deb to APT repository using Docker..."
echo "Package: $DEB_FILE"

# Build Docker image for APT repository creation
docker build -f docker/release/Dockerfile.apt-publish -t noetl-apt-publisher:latest .

# Run container to generate APT repository
docker run --rm \
  -v "$(pwd)/build:/build" \
  -e VERSION="$VERSION" \
  -e ARCH="$ARCH" \
  noetl-apt-publisher:latest

echo ""
echo "✅ APT repository created successfully!"
echo "📁 Location: apt-repo/"
echo ""
echo "Upload to GitHub Pages:"
echo "  1. Create 'apt' branch: git checkout --orphan apt"
echo "  2. Copy files: cp -r apt-repo/* ."
echo "  3. Commit and push: git add . && git commit -m 'Add v${VERSION}' && git push origin apt"
echo "  4. Enable GitHub Pages: Settings > Pages > Source: apt branch"
