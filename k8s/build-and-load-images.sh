#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME="noetl-cluster"

echo -e "${GREEN}Building and Loading Images for Unified NoETL Deployment${NC}"
echo -e "This script will build all necessary Docker images and load them into the Kind cluster."
echo

# Check if Kind cluster exists
if ! kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    echo -e "${RED}Error: Kind cluster '${CLUSTER_NAME}' does not exist.${NC}"
    echo "Please create the cluster first or run the unified deployment script."
    exit 1
fi

echo -e "${GREEN}Building Docker images...${NC}"

# Build NoETL images using the existing build script
echo -e "${YELLOW}Building NoETL images (local-dev and postgres)...${NC}"
cd "${REPO_ROOT}"

# Build the images we need for unified deployment
"${REPO_ROOT}/docker/build-images.sh" --no-pip --tag latest

# Check if images were built successfully
echo -e "${GREEN}Checking built images...${NC}"
IMAGES_TO_CHECK=("noetl-local-dev:latest" "postgres-noetl:latest")
MISSING_IMAGES=()

for image in "${IMAGES_TO_CHECK[@]}"; do
    if ! docker images --format "table {{.Repository}}:{{.Tag}}" | grep -q "^${image}$"; then
        MISSING_IMAGES+=("$image")
    else
        echo -e "${GREEN}✓ Found image: ${image}${NC}"
    fi
done

if [ ${#MISSING_IMAGES[@]} -ne 0 ]; then
    echo -e "${RED}Error: The following images are missing:${NC}"
    for image in "${MISSING_IMAGES[@]}"; do
        echo -e "  ${RED}- ${image}${NC}"
    done
    exit 1
fi

echo -e "${GREEN}Loading images into Kind cluster '${CLUSTER_NAME}'...${NC}"

# Load noetl-local-dev image
echo -e "${YELLOW}Loading noetl-local-dev:latest...${NC}"
kind load docker-image noetl-local-dev:latest --name "${CLUSTER_NAME}"

# Load postgres image
echo -e "${YELLOW}Loading postgres-noetl:latest...${NC}"
kind load docker-image postgres-noetl:latest --name "${CLUSTER_NAME}"

echo -e "${GREEN}Verifying images in cluster...${NC}"
# Verify images are loaded in the cluster
docker exec "${CLUSTER_NAME}-control-plane" crictl images | grep -E "(noetl|postgres)" || {
    echo -e "${YELLOW}No images found with crictl, checking with docker...${NC}"
    docker exec "${CLUSTER_NAME}-control-plane" docker images | grep -E "(noetl|postgres)" || {
        echo -e "${RED}Warning: Could not verify images in cluster${NC}"
    }
}

echo -e "${GREEN}Images successfully built and loaded!${NC}"
echo
echo -e "${YELLOW}Available images in cluster:${NC}"
echo -e "  - noetl-local-dev:latest (for server and workers)"
echo -e "  - postgres-noetl:latest (for database)"
echo
echo -e "${GREEN}You can now deploy the unified platform:${NC}"
echo -e "  ${YELLOW}./k8s/deploy-unified-platform.sh --no-cluster${NC}"