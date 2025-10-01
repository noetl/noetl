#!/bin/bash
set -euo pipefail

# NoETL Platform Health Check Script
# - Checks Kubernetes pods and services for Postgres and NoETL
# - Optionally waits for readiness
# - Curls NoETL /api/health via NodePort
# - Verifies Postgres readiness using pg_isready inside the pod
#
# Usage:
#   chmod +x k8s/check-status.sh
#   ./k8s/check-status.sh [--namespace NAMESPACE] [--no-wait] [--no-postgres] [--no-noetl] [--no-curl] [--url URL]
#
# Defaults:
#   namespace: noetl (override with --namespace)
#   postgres namespace: postgres (override with --postgres-namespace)
#   wait: true
#   url: http://localhost:30082/health (derived from NodePort if not provided)

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

NAMESPACE="noetl"
POSTGRES_NAMESPACE="postgres"
WAIT_FOR_READY=true
CHECK_POSTGRES=true
CHECK_NOETL=true
DO_CURL=true
CUSTOM_URL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace|-n)
      NAMESPACE="$2"; shift 2;;
    --no-wait)
      WAIT_FOR_READY=false; shift;;
    --no-postgres)
      CHECK_POSTGRES=false; shift;;
    --no-noetl)
      CHECK_NOETL=false; shift;;
    --no-curl)
      DO_CURL=false; shift;;
    --url)
      CUSTOM_URL="$2"; shift 2;;
    --postgres-namespace)
      POSTGRES_NAMESPACE="$2"; shift 2;;
    --help|-h)
      echo "Usage: $0 [--namespace NAMESPACE] [--no-wait] [--no-postgres] [--no-noetl] [--no-curl] [--url URL]"; exit 0;;
    *)
      echo -e "${YELLOW}Warning: Unknown option: $1${NC}"; shift;;
  esac
done

if ! command -v kubectl >/dev/null 2>&1; then
  echo -e "${RED}Error: kubectl is not installed or not in PATH.${NC}" >&2
  exit 1
fi

# Confirm cluster accessibility
if ! kubectl version --short >/dev/null 2>&1; then
  echo -e "${RED}Error: Unable to communicate with Kubernetes cluster using kubectl.${NC}" >&2
  exit 1
fi

function noetl_ns_flag() {
  echo "-n ${NAMESPACE}"
}

function postgres_ns_flag() {
  echo "-n ${POSTGRES_NAMESPACE}"
}

function wait_for() {
  local label="$1"
  local app_name="$2"
  local ns_flag="${3:-$(noetl_ns_flag)}"
  if $WAIT_FOR_READY; then
    echo -e "${GREEN}Waiting for ${app_name} pods to be ready...${NC}"
    kubectl wait ${ns_flag} --for=condition=ready pod -l "${label}" --timeout=180s || {
      echo -e "${YELLOW}Warning: ${app_name} pods not ready within timeout.${NC}"
    }
  fi
}

OVERALL_OK=true

if $CHECK_POSTGRES; then
  echo -e "${GREEN}== Postgres status ==${NC}"
  kubectl get pods $(postgres_ns_flag) -l app=postgres || true
  kubectl get svc $(postgres_ns_flag) postgres || true
  wait_for "app=postgres" "Postgres" "$(postgres_ns_flag)"

  # Check pg_isready via exec
  PG_POD="$(kubectl get pod $(postgres_ns_flag) -l app=postgres -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  if [[ -n "$PG_POD" ]]; then
    if kubectl exec $(postgres_ns_flag) "$PG_POD" -- pg_isready -U demo -d demo_noetl -p 5432 >/dev/null 2>&1; then
      echo -e "${GREEN}Postgres readiness OK (pg_isready).${NC}"
    else
      echo -e "${RED}Postgres readiness check failed (pg_isready).${NC}"
      OVERALL_OK=false
    fi
  else
    echo -e "${YELLOW}No Postgres pod found to exec pg_isready.${NC}"
    OVERALL_OK=false
  fi
  echo
fi

if $CHECK_NOETL; then
  echo -e "${GREEN}== NoETL status ==${NC}"
  kubectl get pods $(noetl_ns_flag) -l app=noetl || true
  kubectl get svc $(noetl_ns_flag) noetl || true
  wait_for "app=noetl" "NoETL"

  if $DO_CURL; then
    if [[ -z "$CUSTOM_URL" ]]; then
      # Derive NodePort and construct URL
      NODE_PORT=$(kubectl get svc $(noetl_ns_flag) noetl -o jsonpath='{.spec.ports[?(@.name=="http")].nodePort}' 2>/dev/null || true)
      if [[ -z "$NODE_PORT" ]]; then
        # fallback: first port
        NODE_PORT=$(kubectl get svc $(noetl_ns_flag) noetl -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null || true)
      fi
      if [[ -n "$NODE_PORT" ]]; then
        CUSTOM_URL="http://localhost:${NODE_PORT}/api/health"
      else
        CUSTOM_URL="http://localhost:30082/health"
      fi
    fi
    echo -e "Curling NoETL health: ${CUSTOM_URL}"
    if command -v curl >/dev/null 2>&1; then
      if curl -fsS "$CUSTOM_URL" | sed -e 's/^/  /'; then
        echo -e "${GREEN}NoETL HTTP health OK.${NC}"
      else
        echo -e "${RED}NoETL HTTP health check failed.${NC}"
        OVERALL_OK=false
      fi
    else
      echo -e "${YELLOW}curl not available, skipping HTTP health check.${NC}"
    fi
  fi
  echo
fi

# Summary
if $OVERALL_OK; then
  echo -e "${GREEN}All checks passed.${NC}"
  exit 0
else
  echo -e "${RED}One or more checks failed. See output above for details.${NC}"
  exit 1
fi
