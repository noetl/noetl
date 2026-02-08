#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
K8S_DIR="${REPO_ROOT}/k8s/noetl"
DOCKER_DIR="${REPO_ROOT}/docker"

BUILD_PIP=true
BUILD_LOCAL_DEV=true
PUSH_IMAGES=false
REGISTRY=""
TAG="latest"
PROGRESS_PLAIN=false

function show_usage {
    echo "Usage: $0 [options]"
    echo "Options:"
    echo "  --no-pip            Skip building NoETL pip-version (PyPI) image"
    echo "  --no-local-dev      Skip building NoETL local-dev (local path) image"
    echo "  --push              Push images to registry"
    echo "  --registry REGISTRY Registry to push images to e.g., 'localhost:5000/'"
    echo "  --tag TAG           Tag for the images. Default: latest"
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
        --no-pip)
            BUILD_PIP=false
            shift
            ;;
        --no-local-dev)
            BUILD_LOCAL_DEV=false
            shift
            ;;
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

echo -e "${YELLOW}NoETL Docker Image Build Script (NoETL Images Only)${NC}"
echo "This script will build NoETL Docker images for deployments."
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
    echo "Install docker to build the images."
    exit 1
fi

# Configure docker build progress mode
BUILD_PROGRESS_ARGS=""
if $PROGRESS_PLAIN; then
    export DOCKER_BUILDKIT=1
    BUILD_PROGRESS_ARGS="--progress=plain"
    echo -e "${GREEN}Using BuildKit plain progress for detailed output.${NC}"
fi

if $BUILD_PIP; then
    echo -e "${GREEN}Building NoETL pip-version (PyPI) image...${NC}"
    # Use a minimal build context for the pip image (it does not COPY repo files)
    PIP_CONTEXT="${DOCKER_DIR}/noetl/pip"
    if command -v du &> /dev/null; then
        PIP_CONTEXT_SIZE_HUMAN=$(du -sh "${PIP_CONTEXT}" 2>/dev/null | awk '{print $1}')
        echo -e "Using minimal build context for pip image: ${PIP_CONTEXT} (approx size: ${PIP_CONTEXT_SIZE_HUMAN})"
    else
        echo -e "Using minimal build context for pip image: ${PIP_CONTEXT}"
    fi
    echo -e "Note: If it seems idle, Docker may be transferring the build context. A .dockerignore reduces context size."
    BUILD_START_TS=$(date +%s)
    docker build ${BUILD_PROGRESS_ARGS} -t "${REGISTRY}noetl-pip:${TAG}" -f "${DOCKER_DIR}/noetl/pip/Dockerfile" "${PIP_CONTEXT}"
    BUILD_END_TS=$(date +%s)
    echo -e "${GREEN}pip-version build finished in $((BUILD_END_TS - BUILD_START_TS))s.${NC}"
    
    if $PUSH_IMAGES && [ -n "$REGISTRY" ]; then
        echo -e "${GREEN}Pushing NoETL pip-version image to registry...${NC}"
        docker push "${REGISTRY}noetl-pip:${TAG}"
    fi
else
    echo -e "${YELLOW}Skipping NoETL pip-version image build as requested.${NC}"
fi

if $BUILD_LOCAL_DEV; then
    echo -e "${GREEN}Building NoETL local-dev (local path) image...${NC}"
    echo -e "Note: If it seems idle, Docker may be transferring the build context. A .dockerignore reduces context size."
    BUILD_START_TS=$(date +%s)
    docker build ${BUILD_PROGRESS_ARGS} -t "${REGISTRY}noetl-local-dev:${TAG}" -f "${DOCKER_DIR}/noetl/dev/Dockerfile" "${REPO_ROOT}"
    BUILD_END_TS=$(date +%s)
    echo -e "${GREEN}local-dev build finished in $((BUILD_END_TS - BUILD_START_TS))s.${NC}"
    
    if $PUSH_IMAGES && [ -n "$REGISTRY" ]; then
        echo -e "${GREEN}Pushing NoETL local-dev image to registry...${NC}"
        docker push "${REGISTRY}noetl-local-dev:${TAG}"
    fi
else
    echo -e "${YELLOW}Skipping NoETL local-dev image build as requested.${NC}"
fi

echo -e "${GREEN}NoETL Docker image build completed.${NC}"
echo "The following NoETL images are now available:"
if $BUILD_PIP; then
    echo -e "  - ${YELLOW}${REGISTRY}noetl-pip:${TAG}${NC}"
fi
if $BUILD_LOCAL_DEV; then
    echo -e "  - ${YELLOW}${REGISTRY}noetl-local-dev:${TAG}${NC}"
fi

echo
echo -e "${GREEN}To use these images in Kubernetes:${NC}"
echo -e "  1. Load them into Kind: kind load docker-image <image> --name noetl"
echo -e "  2. Update the deployment YAML files to use these images"
echo -e "  3. Apply deployments: kubectl apply -f ci/manifests/noetl/"
echo
echo -e "${YELLOW}Example workflow:${NC}"
echo -e "  noetl run automation/boot.yaml"