#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
K8S_DIR="${REPO_ROOT}/k8s/noetl"
DOCKER_DIR="${REPO_ROOT}/docker"

PUSH_IMAGES=false
REGISTRY=""
TAG="latest"
PROGRESS_PLAIN=false

function show_usage {
    echo "Usage: $0 [options]"
    echo "Options:"
    echo "  --push              Push image to registry"
    echo "  --registry REGISTRY Registry to push image to e.g., 'localhost:5000/'"
    echo "  --tag TAG           Tag for the image. Default: latest"
    echo "  --plain             Show detailed docker build steps (enables BuildKit plain progress)"
    echo "  --help              Show this help message"
    
    if [ -n "$1" ]; then
        exit 1
    else
        exit 0
    fi
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --push)
            PUSH_IMAGES=true
            shift
            ;;
        --registry)
            REGISTRY="$2/"
            shift 2
            ;;
        --tag)
            TAG="$2"
            shift 2
            ;;
        --plain)
            PROGRESS_PLAIN=true
            shift
            ;;
        --help)
            show_usage
            ;;
        *)
            echo -e "${RED}Error: Unknown option: $1${NC}"
            show_usage "error"
            ;;
    esac
done

echo -e "${YELLOW}PostgreSQL Docker Image Build Script${NC}"
echo "This script will build the PostgreSQL image with NoETL schema."
echo
# Show environment context for better visibility
if command -v docker &> /dev/null; then
    echo -e "Docker version: $(docker --version)"
fi
echo -e "Start time: $(date)"
# Show repository root and an estimate of context size (may take a moment)
if command -v du &> /dev/null; then
    CONTEXT_SIZE_HUMAN=$(du -sh "${REPO_ROOT}" 2>/dev/null | awk '{print $1}')
    CONTEXT_SIZE_KB=$(du -sk "${REPO_ROOT}" 2>/dev/null | awk '{print $1}')
    echo -e "Build context: ${REPO_ROOT} (approx size: ${CONTEXT_SIZE_HUMAN})"
    if [ -n "$CONTEXT_SIZE_KB" ] && [ "$CONTEXT_SIZE_KB" -gt 500000 ]; then
        echo -e "${YELLOW}Warning:${NC} Large build context detected. Consider adjusting .dockerignore to speed up builds."
    fi
else
    echo -e "Build context: ${REPO_ROOT}"
fi

if ! $PROGRESS_PLAIN; then
    echo -e "${YELLOW}Tip:${NC} For detailed step-by-step build logs, re-run with the ${YELLOW}--plain${NC} flag."
fi

if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: docker is not installed.${NC}"
    echo "Install docker to build the image."
    exit 1
fi

# Configure docker build progress mode
BUILD_PROGRESS_ARGS=""
if $PROGRESS_PLAIN; then
    export DOCKER_BUILDKIT=1
    BUILD_PROGRESS_ARGS="--progress=plain"
    echo -e "${GREEN}Using BuildKit plain progress for detailed output.${NC}"
fi

echo -e "${GREEN}Building PostgreSQL image with NoETL schema...${NC}"
echo -e "Note: If it seems idle, Docker may be transferring the build context. A .dockerignore reduces context size."
BUILD_START_TS=$(date +%s)
docker build ${BUILD_PROGRESS_ARGS} -t "${REGISTRY}postgres-noetl:${TAG}" -f "${DOCKER_DIR}/postgres/Dockerfile" "${REPO_ROOT}"
BUILD_END_TS=$(date +%s)
echo -e "${GREEN}PostgreSQL build finished in $((BUILD_END_TS - BUILD_START_TS))s.${NC}"

if $PUSH_IMAGES && [ -n "$REGISTRY" ]; then
    echo -e "${GREEN}Pushing PostgreSQL image to registry...${NC}"
    docker push "${REGISTRY}postgres-noetl:${TAG}"
fi

echo -e "${GREEN}PostgreSQL Docker image build completed.${NC}"
echo "The following PostgreSQL image is now available:"
echo -e "  - ${YELLOW}${REGISTRY}postgres-noetl:${TAG}${NC}"

echo
echo -e "${GREEN}To use this image in Kubernetes:${NC}"
echo -e "  1. Load it into Kind: k8s/load-postgres-image.sh"
echo -e "  2. Update PostgreSQL deployment YAML to use this image"
echo -e "  3. Apply the updated deployment files with kubectl"
echo
echo -e "${YELLOW}Note:${NC} PostgreSQL schema changes are typically applied via:"
echo -e "  make postgres-reset-schema"