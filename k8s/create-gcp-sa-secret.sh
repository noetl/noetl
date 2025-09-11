#!/usr/bin/env bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

SA_FILE_DEFAULT="${REPO_DIR}/.secrets/noetl-service-account.json"
SECRET_NAME="noetl-gcp-service-account"
NAMESPACE="default"

show_usage(){
  cat <<EOF
Usage: $0 [--file PATH] [--namespace NAMESPACE]

Creates or updates the Kubernetes Secret '${SECRET_NAME}' from a local service account JSON file.
Defaults:
  --file       ${SA_FILE_DEFAULT}
  --namespace  ${NAMESPACE}

The secret will contain key: noetl-service-account.json
EOF
}

SA_FILE="${SA_FILE_DEFAULT}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --file)
      SA_FILE="$2"; shift 2;;
    --namespace)
      NAMESPACE="$2"; shift 2;;
    --help|-h)
      show_usage; exit 0;;
    *)
      echo -e "${YELLOW}Warning: Unknown option $1${NC}"; shift;;
  esac
done

if ! command -v kubectl >/dev/null 2>&1; then
  echo -e "${RED}Error: kubectl not found in PATH.${NC}"; exit 1
fi

if [[ ! -f "${SA_FILE}" ]]; then
  echo -e "${YELLOW}Warning: Service account file not found at:${NC} ${SA_FILE}"
  echo -e "${YELLOW}Skipping creation of secret '${SECRET_NAME}'. Mounts will fail if deployment expects it.${NC}"
  exit 0
fi

echo -e "${GREEN}Creating/updating Secret '${SECRET_NAME}' in namespace '${NAMESPACE}' from:${NC} ${YELLOW}${SA_FILE}${NC}"
kubectl create secret generic "${SECRET_NAME}" \
  --namespace "${NAMESPACE}" \
  --from-file=noetl-service-account.json="${SA_FILE}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo -e "${GREEN}Secret '${SECRET_NAME}' is ensured in namespace '${NAMESPACE}'.${NC}"
