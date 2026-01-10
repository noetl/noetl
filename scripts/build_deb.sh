#!/bin/bash
set -e

VERSION=${1:-2.5.3}
ARCH=$(dpkg --print-architecture)
BUILD_DIR="/tmp/noetl-deb-build"

echo "📦 Building NoETL .deb package v${VERSION} for ${ARCH}..."

# Clean previous builds
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# Clone or copy source
if [ -d ".git" ]; then
    echo "📂 Using current repository..."
    REPO_DIR=$(pwd)
else
    echo "📥 Cloning repository..."
    git clone https://github.com/noetl/noetl.git "$BUILD_DIR/noetl-${VERSION}"
    REPO_DIR="$BUILD_DIR/noetl-${VERSION}"
    cd "$REPO_DIR"
    git checkout "v${VERSION}"
fi

# Install build dependencies (if not already installed)
echo "🔧 Checking build dependencies..."
if ! command -v cargo &> /dev/null; then
    echo "❌ Rust/Cargo not found. Install with:"
    echo "   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
    exit 1
fi

if ! command -v dpkg-deb &> /dev/null; then
    echo "❌ dpkg-deb not found. Install with:"
    echo "   sudo apt-get install dpkg-dev"
    exit 1
fi

# Build Rust binary
echo "🔨 Building Rust binary..."
cd "$REPO_DIR"
cargo build --release -p noetl-cli

# Create debian package structure
PKG_DIR="$BUILD_DIR/noetl_${VERSION}-1_${ARCH}"
mkdir -p "$PKG_DIR/DEBIAN"
mkdir -p "$PKG_DIR/usr/bin"

# Copy binary
cp target/release/noetl "$PKG_DIR/usr/bin/"
chmod 0755 "$PKG_DIR/usr/bin/noetl"

# Create control file
cat > "$PKG_DIR/DEBIAN/control" <<EOF
Package: noetl
Version: ${VERSION}-1
Section: utils
Priority: optional
Architecture: ${ARCH}
Maintainer: NoETL Team <support@noetl.io>
Homepage: https://noetl.io
Description: NoETL workflow automation CLI
 NoETL is a workflow automation framework for data processing
 and MLOps orchestration with a distributed server-worker architecture.
 .
 This package provides the noetl command-line interface for:
  - Local playbook execution without server infrastructure
  - Server and worker process management
  - Resource management (playbooks and credentials)
  - Kubernetes cluster operations
  - Database schema management
EOF

# Build .deb package
echo "📦 Creating .deb package..."
dpkg-deb --build "$PKG_DIR"

# Move to output directory
OUTPUT_DIR="$REPO_DIR/build/deb"
mkdir -p "$OUTPUT_DIR"
mv "$PKG_DIR.deb" "$OUTPUT_DIR/noetl_${VERSION}-1_${ARCH}.deb"

# Generate checksums
cd "$OUTPUT_DIR"
sha256sum "noetl_${VERSION}-1_${ARCH}.deb" > "noetl_${VERSION}-1_${ARCH}.deb.sha256"

echo ""
echo "✅ Package built successfully!"
echo "📦 Location: $OUTPUT_DIR/noetl_${VERSION}-1_${ARCH}.deb"
echo "🔐 SHA256: $(cat noetl_${VERSION}-1_${ARCH}.deb.sha256)"
echo ""
echo "Test installation:"
echo "  sudo dpkg -i $OUTPUT_DIR/noetl_${VERSION}-1_${ARCH}.deb"
echo "  noetl --version"
