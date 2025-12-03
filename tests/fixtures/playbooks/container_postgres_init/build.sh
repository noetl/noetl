#!/bin/bash
set -euo pipefail

# build.sh - Build and load container test image into Kind cluster
# Usage: ./build.sh [kind-cluster-name]

CLUSTER_NAME="${1:-noetl}"
IMAGE_NAME="noetl/postgres-container-test:latest"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==================================================="
echo "Container Test Image Build and Load"
echo "==================================================="
echo "Image: $IMAGE_NAME"
echo "Cluster: $CLUSTER_NAME"
echo "Build context: $SCRIPT_DIR"
echo "==================================================="
echo ""

# Step 1: Build Docker image
echo "Step 1: Building Docker image..."
docker build -t "$IMAGE_NAME" "$SCRIPT_DIR"
echo "✓ Image built successfully"
echo ""

# Step 2: Verify image exists
echo "Step 2: Verifying local image..."
if docker images "$IMAGE_NAME" | grep -q postgres-container-test; then
    docker images "$IMAGE_NAME"
    echo "✓ Image verified locally"
else
    echo "ERROR: Image not found locally"
    exit 1
fi
echo ""

# Step 3: Check if Kind cluster exists
echo "Step 3: Checking Kind cluster..."
if ! kind get clusters | grep -q "^${CLUSTER_NAME}$"; then
    echo "ERROR: Kind cluster '$CLUSTER_NAME' not found"
    echo "Available clusters:"
    kind get clusters
    echo ""
    echo "Create cluster with: task kind-create-cluster"
    exit 1
fi
echo "✓ Cluster exists"
echo ""

# Step 4: Load image into Kind
echo "Step 4: Loading image into Kind cluster..."
kind load docker-image "$IMAGE_NAME" --name "$CLUSTER_NAME"
echo "✓ Image loaded into cluster"
echo ""

# Step 5: Verify image in cluster
echo "Step 5: Verifying image in cluster..."
if docker exec -t "${CLUSTER_NAME}-control-plane" crictl images 2>/dev/null | grep -q postgres-container-test; then
    echo "✓ Image available in cluster"
    docker exec -t "${CLUSTER_NAME}-control-plane" crictl images | grep postgres-container-test
else
    echo "WARNING: Could not verify image in cluster (may require admin permissions)"
fi
echo ""

echo "==================================================="
echo "Build and load completed successfully!"
echo "==================================================="
echo ""
echo "Next steps:"
echo "  1. Register playbook: task test:container:register"
echo "  2. Execute playbook: task test:container:execute"
echo "  3. Verify results: task test:container:verify"
echo ""
echo "Or run full test: task test:container:full"
echo ""
