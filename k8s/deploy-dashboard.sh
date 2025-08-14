#!/usr/bin/env bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

INSTALL_METRICS=true
DASHBOARD_VERSION="v2.7.0"

show_usage() {
  echo "Usage: $0 [options]"
  echo "Options:"
  echo "  --no-metrics            Skip installing metrics-server"
  echo "  --dashboard-version VER Use specific dashboard version (default: ${DASHBOARD_VERSION})"
  echo "  --help                  Show this help message"
  if [ -n "${1:-}" ]; then
    exit 1
  else
    exit 0
  fi
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --no-metrics)
      INSTALL_METRICS=false
      shift
      ;;
    --dashboard-version)
      DASHBOARD_VERSION="$2"
      shift 2
      ;;
    --help)
      show_usage
      ;;
    *)
      echo -e "${RED}Unknown option: $1${NC}"
      show_usage "error"
      ;;
  esac
done

if ! command -v kubectl >/dev/null 2>&1; then
  echo -e "${RED}Error: kubectl is not installed or not in PATH.${NC}"
  exit 1
fi

CURRENT_CONTEXT=$(kubectl config current-context || true)
if [ -z "$CURRENT_CONTEXT" ]; then
  echo -e "${RED}Error: kubectl has no current context set.${NC}"
  exit 1
fi

echo -e "${GREEN}Deploying Kubernetes Dashboard (${DASHBOARD_VERSION}) to context:${NC} ${YELLOW}$CURRENT_CONTEXT${NC}"

DASHBOARD_URL="https://raw.githubusercontent.com/kubernetes/dashboard/${DASHBOARD_VERSION}/aio/deploy/recommended.yaml"
echo -e "${GREEN}Applying Dashboard manifest:${NC} ${YELLOW}${DASHBOARD_URL}${NC}"
kubectl apply -f "${DASHBOARD_URL}"

if $INSTALL_METRICS; then
  METRICS_URL="https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml"
  echo -e "${GREEN}Applying metrics-server manifest:${NC} ${YELLOW}${METRICS_URL}${NC}"
  kubectl apply -f "${METRICS_URL}" || echo -e "${YELLOW}Warning: metrics-server apply failed. Continuing...${NC}"
else
  echo -e "${YELLOW}Skipping metrics-server installation as requested.${NC}"
fi

NS="kubernetes-dashboard"
echo -e "${GREEN}Waiting for Dashboard pods to be ready in namespace '${NS}'...${NC}"
kubectl get ns "$NS" >/dev/null 2>&1 || true
sleep 3
kubectl rollout status deployment/kubernetes-dashboard -n "$NS" --timeout=180s || echo -e "${YELLOW}Warning: rollout status timed out or failed. Checking pod status...${NC}"
kubectl get pods -n "$NS" -o wide || true

SA_NAME="dashboard-admin-sa"
CRB_NAME="dashboard-admin-sa"

if kubectl get serviceaccount "$SA_NAME" -n "$NS" >/dev/null 2>&1; then
  echo -e "${YELLOW}ServiceAccount '${SA_NAME}' already exists in namespace '${NS}'. Skipping creation.${NC}"
else
  echo -e "${GREEN}Creating ServiceAccount '${SA_NAME}' in namespace '${NS}'...${NC}"
  kubectl create serviceaccount "$SA_NAME" -n "$NS"
fi

if kubectl get clusterrolebinding "$CRB_NAME" >/dev/null 2>&1; then
  echo -e "${YELLOW}ClusterRoleBinding '${CRB_NAME}' already exists. Skipping creation.${NC}"
else
  echo -e "${GREEN}Creating ClusterRoleBinding '${CRB_NAME}' to cluster-admin for SA '${SA_NAME}'...${NC}"
  kubectl create clusterrolebinding "$CRB_NAME" \
    --clusterrole=cluster-admin \
    --serviceaccount="${NS}:${SA_NAME}"
fi

TOKEN=""
CREATE_TOKEN_SUPPORTED=true
if ! kubectl -n "$NS" create token "$SA_NAME" >/dev/null 2>&1; then
  CREATE_TOKEN_SUPPORTED=false
fi

if $CREATE_TOKEN_SUPPORTED; then
  echo -e "${GREEN}Generating login token using 'kubectl create token'...${NC}"
  TOKEN=$(kubectl -n "$NS" create token "$SA_NAME" || true)
fi

if [ -z "$TOKEN" ]; then
  echo -e "${YELLOW}Falling back to reading token from a Secret attached to the ServiceAccount...${NC}"
  TOKEN_NAME=$(kubectl -n "$NS" get sa/"$SA_NAME" -o jsonpath="{.secrets[0].name}" 2>/dev/null || true)
  if [ -n "$TOKEN_NAME" ]; then
    TOKEN=$(kubectl -n "$NS" get secret "$TOKEN_NAME" -o jsonpath="{.data.token}" 2>/dev/null | base64 --decode || true)
  fi
fi

if [ -z "$TOKEN" ]; then
  echo -e "${YELLOW}Could not automatically retrieve a token.${NC}"
  echo -e "This might happen if your cluster version auto-mounts tokens via projected service account tokens only."
  echo -e "If supported, try: ${YELLOW}kubectl -n ${NS} create token ${SA_NAME}${NC}"
else
  echo -e "${GREEN}Dashboard access token:${NC}"
  echo "$TOKEN"
fi

DASHBOARD_URL_LOCAL="http://localhost:8001/api/v1/namespaces/${NS}/services/https:kubernetes-dashboard:/proxy/"
cat <<EOT

${GREEN}Dashboard deployed successfully.${NC}

Access instructions:
  1) Start the kubectl proxy in a separate terminal:
       ${YELLOW}kubectl proxy${NC}
  2) Open the Dashboard in your browser:
       ${YELLOW}${DASHBOARD_URL_LOCAL}${NC}
  3) When prompted, choose token-based login and paste the token printed above.

Troubleshooting:
  - Check pods:        ${YELLOW}kubectl get pods -n ${NS}${NC}
  - Dashboard logs:    ${YELLOW}kubectl logs -n ${NS} -l k8s-app=kubernetes-dashboard${NC}
  - Metrics-Server:    ${YELLOW}kubectl get pods -n kube-system | grep metrics-server${NC}

EOT
