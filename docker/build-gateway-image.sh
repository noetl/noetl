#!/usr/bin/env bash
set -euo pipefail

# Build and load Gateway image into kind cluster
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Building Gateway Docker image..."
cd "$PROJECT_ROOT/crates/gateway"

docker buildx build --load --platform linux/amd64 -t noetl-gateway:latest -f Dockerfile .

echo "Loading Gateway image into kind cluster..."
kind load docker-image noetl-gateway:latest --name noetl

echo "Gateway image built and loaded into kind cluster"
