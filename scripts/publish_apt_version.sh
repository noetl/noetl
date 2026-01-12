#!/bin/bash
set -e

# Script to publish a new version to the APT repository
# Usage: ./scripts/publish_apt_version.sh <version> [architecture]
# Example: ./scripts/publish_apt_version.sh 2.5.4 arm64

VERSION=${1:-}
ARCH=${2:-arm64}

if [ -z "$VERSION" ]; then
    echo "Usage: $0 <version> [architecture]"
    echo "Example: $0 2.5.4 arm64"
    exit 1
fi

echo "Publishing NoETL version $VERSION to APT repository..."

# Step 1: Build Debian package
echo "Step 1: Building Debian package..."
./docker/release/build-deb-docker.sh "$VERSION"

if [ ! -f "build/deb/noetl_${VERSION}-1_${ARCH}.deb" ]; then
    echo "Error: Debian package not found at build/deb/noetl_${VERSION}-1_${ARCH}.deb"
    exit 1
fi

echo "✅ Debian package built: build/deb/noetl_${VERSION}-1_${ARCH}.deb"

# Step 2: Generate APT repository
echo "Step 2: Generating APT repository..."
./docker/release/publish-apt-docker.sh "$VERSION" "$ARCH"

if [ ! -d "build/apt-repo" ]; then
    echo "Error: APT repository not found at build/apt-repo/"
    exit 1
fi

echo "✅ APT repository generated"

# Step 3: Update apt branch
echo "Step 3: Updating apt branch on GitHub..."

# Save current branch
CURRENT_BRANCH=$(git branch --show-current)

# Checkout apt branch
git fetch origin apt:apt 2>/dev/null || true
git checkout apt

# Copy new APT repository files
cp -r build/apt-repo/dists/* dists/
cp -r build/apt-repo/pool/* pool/

# Commit and push
git add dists/ pool/
git commit -m "Release NoETL v${VERSION} for ${ARCH}"
git push origin apt

echo "✅ APT repository updated on GitHub"
echo ""
echo "GitHub Actions will automatically deploy to https://noetl.github.io/noetl"
echo "Check deployment status: https://github.com/noetl/noetl/actions/workflows/pages.yml"
echo ""
echo "Users can install with:"
echo "  echo 'deb [trusted=yes] https://noetl.github.io/noetl jammy main' | sudo tee /etc/apt/sources.list.d/noetl.list"
echo "  sudo apt update"
echo "  sudo apt install noetl"

# Return to original branch
git checkout "$CURRENT_BRANCH"

echo ""
echo "✅ Done! You are back on branch: $CURRENT_BRANCH"
