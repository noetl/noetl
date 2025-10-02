#!/bin/bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

DEPLOYMENT_TYPE="dev"
REPO_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_PATH=""
VERSION=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --type)
      DEPLOYMENT_TYPE="$2"
      shift 2
      ;;
    --repo-path)
      REPO_PATH="$2"
      shift 2
      ;;
    --package-path)
      PACKAGE_PATH="$2"
      shift 2
      ;;
    --version)
      VERSION="$2"
      shift 2
      ;;
    --help)
      echo "Usage: $0 [options]"
      echo "Options:"
      echo "  --type TYPE         Deployment type: dev, package, version (default: dev)"
      echo "  --repo-path PATH    Path to local NoETL repository (for dev type)"
      echo "  --package-path PATH Path to directory with NoETL package files (for package type)"
      echo "  --version VERSION   NoETL version to install from PyPI (for version type)"
      echo "  --help              Show this help message"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

echo -e "${YELLOW}Deploying NoETL (${DEPLOYMENT_TYPE} mode)${NC}"

if [[ "$DEPLOYMENT_TYPE" == "dev" && ! -d "$REPO_PATH" ]]; then
  echo -e "${RED}Error: Repository path does not exist: $REPO_PATH${NC}"
  exit 1
fi

if [[ "$DEPLOYMENT_TYPE" == "package" && ! -d "$PACKAGE_PATH" ]]; then
  echo -e "${RED}Error: Package path does not exist: $PACKAGE_PATH${NC}"
  exit 1
fi

if [[ "$DEPLOYMENT_TYPE" == "version" && -z "$VERSION" ]]; then
  echo -e "${YELLOW}Warning: No version specified, using latest${NC}"
  VERSION="latest"
fi

BUILD_IMAGES=true
if $BUILD_IMAGES; then
  echo -e "${GREEN}Building Docker images for NoETL deployments...${NC}"
  "${REPO_PATH}/docker/build-images.sh" --no-pip
  echo -e "${GREEN}Docker images built successfully.${NC}"
  
  if kubectl config current-context | grep -q "kind-"; then
    echo -e "${GREEN}Loading Docker images into Kind cluster...${NC}"
    "${SCRIPT_DIR}/load-images.sh" --no-pip --cluster-name "$(kubectl config current-context | sed 's/^kind-//')"
    echo -e "${GREEN}Docker images loaded successfully.${NC}"
  fi
fi

if [[ "$DEPLOYMENT_TYPE" == "dev" ]]; then
  echo -e "${GREEN}Creating development deployment using noetl-local-dev Docker image${NC}"
  cp "${SCRIPT_DIR}/noetl/noetl-dev-deployment.yaml" /tmp/noetl-deployment.yaml
elif [[ "$DEPLOYMENT_TYPE" == "package" ]]; then
  echo -e "${GREEN}Creating package deployment with package at: $PACKAGE_PATH${NC}"
  sed "s|path: /path/to/local/noetl/package|path: $PACKAGE_PATH|g" \
    "${SCRIPT_DIR}/noetl/noetl-package-deployment.yaml" > /tmp/noetl-deployment.yaml
elif [[ "$DEPLOYMENT_TYPE" == "version" ]]; then
  echo -e "${GREEN}Creating version-specific deployment with version: $VERSION${NC}"
  if [[ "$VERSION" == "latest" ]]; then
    sed "s|value: \"1.0.0\"|value: \"latest\"|g" \
      "${SCRIPT_DIR}/noetl/noetl-version-deployment.yaml" > /tmp/noetl-deployment.yaml
  else
    sed "s|value: \"1.0.0\"|value: \"$VERSION\"|g" \
      "${SCRIPT_DIR}/noetl/noetl-version-deployment.yaml" > /tmp/noetl-deployment.yaml
  fi
else
  echo -e "${RED}Error: Unknown deployment type: $DEPLOYMENT_TYPE${NC}"
  exit 1
fi

if ! command -v kubectl &> /dev/null; then
  echo -e "${RED}Error: kubectl is not installed.${NC}"
  echo "Install kubectl to deploy NoETL."
  exit 1
fi

echo -e "${GREEN}Checking for existing NoETL deployments...${NC}"
if kubectl get deployment noetl-dev &> /dev/null; then
  echo -e "${GREEN}Deleting existing noetl-dev deployment...${NC}"
  kubectl delete deployment noetl-dev
fi

if kubectl get deployment noetl-package &> /dev/null; then
  echo -e "${GREEN}Deleting existing noetl-package deployment...${NC}"
  kubectl delete deployment noetl-package
fi

if kubectl get deployment noetl-version &> /dev/null; then
  echo -e "${GREEN}Deleting existing noetl-version deployment...${NC}"
  kubectl delete deployment noetl-version
fi

echo -e "${GREEN}Applying ConfigMap and Secret...${NC}"
kubectl apply -f "${SCRIPT_DIR}/noetl/noetl-configmap.yaml"
kubectl apply -f "${SCRIPT_DIR}/noetl/noetl-secret.yaml" || echo -e "${YELLOW}Warning: Secret not found or could not be applied${NC}"

echo -e "${GREEN}Applying NoETL deployment...${NC}"
kubectl apply -f /tmp/noetl-deployment.yaml

if [[ "$DEPLOYMENT_TYPE" == "dev" ]]; then
  if ! kubectl get service noetl-dev &> /dev/null; then
    echo -e "${GREEN}Applying NoETL development service...${NC}"
    kubectl apply -f "${SCRIPT_DIR}/noetl/noetl-dev-service.yaml"
  else
    echo -e "${GREEN}NoETL development service already exists, skipping...${NC}"
  fi
else
  if ! kubectl get service noetl &> /dev/null; then
    echo -e "${GREEN}Applying NoETL service...${NC}"
    kubectl apply -f "${SCRIPT_DIR}/noetl/noetl-service.yaml"
  else
    echo -e "${GREEN}NoETL service already exists, skipping...${NC}"
  fi
fi

echo -e "${GREEN}Waiting for NoETL to be ready...${NC}"
sleep 5
kubectl get pods -l app=noetl-$DEPLOYMENT_TYPE

echo -e "${GREEN}NoETL deployment complete!${NC}"
ACCESS_URL=""
if [[ "$DEPLOYMENT_TYPE" == "dev" ]]; then
  if kubectl get service noetl-dev >/dev/null 2>&1; then
    NODE_PORT=$(kubectl get svc noetl-dev -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null || true)
    if [[ -n "$NODE_PORT" ]]; then
      ACCESS_URL="http://localhost:${NODE_PORT}/api/health"
    fi
  fi
  if [[ -z "$ACCESS_URL" ]]; then
    ACCESS_URL="http://localhost:30080/api/health"
  fi
else
  if kubectl get service noetl >/dev/null 2>&1; then
    NODE_PORT=$(kubectl get svc noetl -o jsonpath='{.spec.ports[?(@.name=="http")].nodePort}' 2>/dev/null || true)
    if [[ -z "$NODE_PORT" ]]; then
      NODE_PORT=$(kubectl get svc noetl -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null || true)
    fi
    if [[ -n "$NODE_PORT" ]]; then
      ACCESS_URL="http://localhost:${NODE_PORT}/api/health"
    fi
  fi
  if [[ -z "$ACCESS_URL" ]]; then
    ACCESS_URL="http://localhost:30082/health"
  fi
fi

echo "You can access NoETL at: ${ACCESS_URL} if using NodePort service"
