#!/bin/bash
set -e

# Complete build process: Rust binaries + Docker images
# Usage: ./scripts/build_all.sh [--multiarch] [--push] [--tag TAG]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MULTIARCH=false
PUSH=false
TAG="local/noetl:latest"
BUILD_RUST=true

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --multiarch)
            MULTIARCH=true
            shift
            ;;
        --push)
            PUSH=true
            shift
            ;;
        --tag)
            TAG="$2"
            shift 2
            ;;
        --skip-rust)
            BUILD_RUST=false
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--multiarch] [--push] [--tag TAG] [--skip-rust]"
            exit 1
            ;;
    esac
done

cd "$PROJECT_ROOT"

echo "==================================================================="
echo "NoETL Complete Build Process"
echo "==================================================================="
echo "Multi-arch Docker: $MULTIARCH"
echo "Push to registry:  $PUSH"
echo "Docker tag:        $TAG"
echo "Build Rust CLI:    $BUILD_RUST"
echo ""

# Step 1: Build Rust CLI for Linux platforms (if not skipped)
if [ "$BUILD_RUST" = true ]; then
    echo "Step 1: Building Rust CLI for Linux platforms..."
    echo "-------------------------------------------------------------------"
    
    cd noetlctl
    
    # Install cross if needed
    if ! command -v cross &> /dev/null; then
        echo "Installing cross for cross-compilation..."
        cargo install cross --locked
    fi
    
    # Build for x86_64 Linux (most common)
    echo "Building for x86_64-unknown-linux-gnu..."
    cross build --release --target x86_64-unknown-linux-gnu
    
    # Build for ARM64 Linux
    echo "Building for aarch64-unknown-linux-gnu..."
    cross build --release --target aarch64-unknown-linux-gnu
    
    # Build for local platform if on Mac
    if [[ "$OSTYPE" == "darwin"* ]]; then
        ARCH=$(uname -m)
        echo "Building for local Mac platform ($ARCH)..."
        cargo build --release
        
        # Copy to bin/
        mkdir -p "$PROJECT_ROOT/bin"
        cp target/release/noetl "$PROJECT_ROOT/bin/noetl"
        echo "✓ Local binary copied to bin/noetl"
    fi
    
    cd "$PROJECT_ROOT"
    echo "✓ Rust binaries built"
    echo ""
else
    echo "Step 1: Skipping Rust CLI build (using existing binaries)"
    echo ""
fi

# Step 2: Build Docker images
echo "Step 2: Building Docker images..."
echo "-------------------------------------------------------------------"

if [ "$MULTIARCH" = true ]; then
    # Multi-architecture build with buildx
    echo "Using Docker buildx for multi-platform build..."
    
    # Create/use builder
    if ! docker buildx inspect noetl-builder &> /dev/null; then
        docker buildx create --name noetl-builder --use
    else
        docker buildx use noetl-builder
    fi
    
    BUILD_ARGS="--platform linux/amd64,linux/arm64"
    BUILD_ARGS="$BUILD_ARGS -f docker/noetl/dev/Dockerfile"
    BUILD_ARGS="$BUILD_ARGS -t $TAG"
    
    if [ "$PUSH" = true ]; then
        BUILD_ARGS="$BUILD_ARGS --push"
    else
        echo "WARNING: Multi-arch build without --push will only build, not load locally"
        BUILD_ARGS="$BUILD_ARGS --load"
    fi
    
    docker buildx build $BUILD_ARGS .
    
else
    # Single platform build (current architecture)
    echo "Building for current platform only..."
    docker build -f docker/noetl/dev/Dockerfile -t "$TAG" .
    
    if [ "$PUSH" = true ]; then
        docker push "$TAG"
    fi
fi

echo "✓ Docker image built: $TAG"
echo ""

# Step 3: Summary
echo "==================================================================="
echo "Build Complete!"
echo "==================================================================="
echo "Docker image:  $TAG"

if [ "$BUILD_RUST" = true ]; then
    echo "Rust binaries:"
    echo "  - noetlctl/target/x86_64-unknown-linux-gnu/release/noetl"
    echo "  - noetlctl/target/aarch64-unknown-linux-gnu/release/noetl"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "  - bin/noetl (local Mac)"
    fi
fi

echo ""
echo "To deploy to kind cluster:"
echo "  ./bin/noetl k8s deploy"
echo ""
