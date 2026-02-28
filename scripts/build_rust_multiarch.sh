#!/bin/bash
set -e

# Build noetlctl for multiple architectures
# This should be run before building Docker images for multi-platform support

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
NOETLCTL_DIR="$PROJECT_ROOT/noetlctl"

cd "$NOETLCTL_DIR"

echo "=== Building noetlctl for multiple architectures ==="

# Install cross-compilation tools if not already installed
if ! command -v cross &> /dev/null; then
    echo "Installing cross for cross-compilation..."
    cargo install cross
fi

# Build for x86_64 Linux (most common in cloud/Docker)
echo "Building for x86_64-unknown-linux-gnu..."
cross build --release --target x86_64-unknown-linux-gnu

# Build for ARM64 Linux (AWS Graviton, ARM-based cloud instances)
echo "Building for aarch64-unknown-linux-gnu..."
cross build --release --target aarch64-unknown-linux-gnu

# Build for local Mac (if on macOS)
if [[ "$OSTYPE" == "darwin"* ]]; then
    ARCH=$(uname -m)
    if [ "$ARCH" = "arm64" ]; then
        echo "Building for aarch64-apple-darwin (Apple Silicon)..."
        cargo build --release --target aarch64-apple-darwin
    else
        echo "Building for x86_64-apple-darwin (Intel Mac)..."
        cargo build --release --target x86_64-apple-darwin
    fi
    
    # Copy local binary to bin/
    mkdir -p "$PROJECT_ROOT/bin"
    cp target/release/noetl "$PROJECT_ROOT/bin/noetl"
    echo "✓ Copied local binary to bin/noetl"
    # Ad-hoc sign on macOS to prevent Gatekeeper SIGKILL on freshly built binaries
    if [[ "$(uname)" == "Darwin" ]]; then
        codesign --sign - "$PROJECT_ROOT/bin/noetl" 2>/dev/null && echo "✓ Codesigned bin/noetl" || true
    fi
fi

echo ""
echo "=== Build complete ==="
echo "Binaries available at:"
echo "  - target/x86_64-unknown-linux-gnu/release/noetl"
echo "  - target/aarch64-unknown-linux-gnu/release/noetl"
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "  - bin/noetl (local platform)"
fi
echo ""
echo "Use these binaries with Docker multi-platform builds:"
echo "  docker buildx build --platform linux/amd64,linux/arm64 ..."
