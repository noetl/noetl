#!/bin/bash
set -e

# Build Docker image for multi-platform with pre-compiled Rust binaries
# Usage: ./scripts/docker_build_multiplatform.sh [--push] [--tag TAG]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PUSH=false
TAG="local/noetl:latest"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --push)
            PUSH=true
            shift
            ;;
        --tag)
            TAG="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--push] [--tag TAG]"
            exit 1
            ;;
    esac
done

cd "$PROJECT_ROOT"

echo "=== Building multi-platform Docker image ==="
echo "Tag: $TAG"
echo "Push: $PUSH"
echo ""

# Check if buildx is available
if ! docker buildx version &> /dev/null; then
    echo "ERROR: docker buildx is not available"
    echo "Please install Docker Buildx or use Docker Desktop"
    exit 1
fi

# Create builder if it doesn't exist
if ! docker buildx inspect noetl-builder &> /dev/null; then
    echo "Creating buildx builder..."
    docker buildx create --name noetl-builder --use
fi

# Use existing builder
docker buildx use noetl-builder

# Build arguments
BUILD_ARGS="--platform linux/amd64,linux/arm64"
BUILD_ARGS="$BUILD_ARGS -f docker/noetl/dev/Dockerfile"
BUILD_ARGS="$BUILD_ARGS -t $TAG"

if [ "$PUSH" = true ]; then
    BUILD_ARGS="$BUILD_ARGS --push"
else
    BUILD_ARGS="$BUILD_ARGS --load"
fi

echo "Building Docker image..."
docker buildx build $BUILD_ARGS .

echo ""
echo "✓ Docker image built successfully: $TAG"
if [ "$PUSH" = false ]; then
    echo "  (Loaded for local platform only. Use --push for multi-platform registry push)"
fi
