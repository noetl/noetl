#!/bin/bash

# Build and deploy NoETL containers to Google Container Registry
# This script builds the NoETL Docker images and pushes them to GCR

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

PROJECT_ID=""
REGION="us-central1"
IMAGE_TAG="latest"
BUILD_CONTEXT="../../"  # Path to the project root from this script
DOCKERFILE_PATH="docker/noetl/dev/Dockerfile"

SERVER_REPO="gcr.io"
WORKER_REPO="gcr.io"

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_prerequisites() {
    print_status "Checking prerequisites..."
    
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed or not in PATH"
        exit 1
    fi
    
    if ! command -v gcloud &> /dev/null; then
        print_error "Google Cloud SDK is not installed or not in PATH"
        exit 1
    fi
    
    print_success "Prerequisites check passed"
}

configure_docker() {
    print_status "Configuring Docker for Google Container Registry..."
    
    gcloud auth configure-docker --quiet
    
    print_success "Docker configured for GCR"
}

get_project_id() {
    if [ -z "$PROJECT_ID" ]; then
        PROJECT_ID=$(gcloud config get-value project 2>/dev/null || echo "")
        if [ -z "$PROJECT_ID" ]; then
            print_error "No project ID specified and no default project set in gcloud config"
            echo "Please run: gcloud config set project YOUR_PROJECT_ID"
            echo "Or set PROJECT_ID environment variable"
            exit 1
        fi
        print_status "Using project ID from gcloud config: $PROJECT_ID"
    else
        print_status "Using specified project ID: $PROJECT_ID"
    fi
}

build_image() {
    local image_name="$1"
    local target="$2"
    
    print_status "Building $image_name..."
    
    # Full image name with registry
    local full_image_name="${SERVER_REPO}/${PROJECT_ID}/${image_name}:${IMAGE_TAG}"
    
    # Build the image
    docker build \
        --target "$target" \
        --tag "$full_image_name" \
        --file "${BUILD_CONTEXT}/${DOCKERFILE_PATH}" \
        "$BUILD_CONTEXT"
    
    print_success "Built $full_image_name"
    echo "$full_image_name"
}

push_image() {
    local image_name="$1"
    
    print_status "Pushing $image_name to GCR..."
    
    docker push "$image_name"
    
    print_success "Pushed $image_name"
}

build_and_push_all() {
    print_status "Building and pushing NoETL images..."
    
    local server_image
    server_image=$(build_image "noetl-server" "production")
    push_image "$server_image"
    
    local worker_image
    worker_image=$(build_image "noetl-worker" "production")
    push_image "$worker_image"
    
    print_success "All images built and pushed successfully!"
    echo ""
    echo "Server image: $server_image"
    echo "Worker image: $worker_image"
    echo ""
    echo "You can now use these images in your Terraform configuration:"
    echo "  server_image_repository = \"${SERVER_REPO}/${PROJECT_ID}/noetl-server\""
    echo "  worker_image_repository = \"${WORKER_REPO}/${PROJECT_ID}/noetl-worker\""
    echo "  server_image_tag = \"${IMAGE_TAG}\""
    echo "  worker_image_tag = \"${IMAGE_TAG}\""
}

show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Build and push NoETL Docker images to Google Container Registry"
    echo ""
    echo "Options:"
    echo "  -p, --project PROJECT_ID    Google Cloud project ID"
    echo "  -r, --region REGION         Google Cloud region (default: us-central1)"
    echo "  -t, --tag TAG               Image tag (default: latest)"
    echo "  -h, --help                  Show this help message"
    echo ""
    echo "Environment variables:"
    echo "  PROJECT_ID                  Google Cloud project ID"
    echo "  IMAGE_TAG                   Docker image tag"
    echo ""
    echo "Examples:"
    echo "  $0 --project my-project --tag v1.0.0"
    echo "  PROJECT_ID=my-project $0"
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -p|--project)
            PROJECT_ID="$2"
            shift 2
            ;;
        -r|--region)
            REGION="$2"
            shift 2
            ;;
        -t|--tag)
            IMAGE_TAG="$2"
            shift 2
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

main() {
    echo "NoETL Container Build and Deploy Script"
    echo "======================================"
    echo ""
    
    check_prerequisites
    get_project_id
    configure_docker
    build_and_push_all
    
    print_success "Container build and deploy completed successfully!"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
