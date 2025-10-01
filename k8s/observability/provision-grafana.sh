#!/usr/bin/env bash
set -euo pipefail

# Provision Grafana dashboards into the victoria-metrics-k8s-stack Grafana via ConfigMaps
# - Expects namespace 'noetl-platform' (or pass as first arg)
# - Uses Grafana sidecar which watches for ConfigMaps labeled grafana_dashboard=1
# - Places dashboards under folder "NoETL" using annotation grafana_folder
#
# Usage:
#   k8s/observability/provision-grafana.sh [NAMESPACE]
#

NAMESPACE="${1:-noetl-platform}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

DASH_DIR="${REPO_ROOT}/docs/observability/dashboards"
SERVER_JSON="${DASH_DIR}/noetl-server-dashboard.json"
WORKERS_JSON="${DASH_DIR}/noetl-workers-dashboard.json"

need_cmd() { command -v "$1" >/dev/null 2>&1; }
info() { echo "[INFO] $*"; }
warn() { echo "[WARN] $*"; }
err() { echo "[ERROR] $*" 1>&2; }

if ! need_cmd kubectl; then
  err "kubectl is not installed or not in PATH."
  echo "Install kubectl: https://kubernetes.io/docs/tasks/tools/"
  exit 2
fi

# Verify namespace exists
if ! kubectl get ns "$NAMESPACE" >/dev/null 2>&1; then
  err "Namespace '$NAMESPACE' not found."
  echo "Create it or run 'make unified-deploy' first."
  exit 3
fi

missing=false
if [ ! -f "$SERVER_JSON" ]; then
  warn "Dashboard JSON not found: $SERVER_JSON"
  missing=true
fi
if [ ! -f "$WORKERS_JSON" ]; then
  warn "Dashboard JSON not found: $WORKERS_JSON"
  missing=true
fi

if [ "$missing" = true ]; then
  warn "Some dashboards are missing; proceeding with those available."
fi

apply_cm() {
  local name="$1"; shift
  local file="$1"; shift
  if [ ! -f "$file" ]; then
    return 0
  fi
  info "Applying ConfigMap $name from $file"
  kubectl -n "$NAMESPACE" create configmap "$name" \
    --from-file="$(basename "$file")=$file" \
    -o yaml --dry-run=client | kubectl apply -f -
  # Label for Grafana sidecar to pick up dashboards
  kubectl -n "$NAMESPACE" label cm "$name" grafana_dashboard=1 --overwrite >/dev/null 2>&1 || true
  # Put into a nice folder inside Grafana
  kubectl -n "$NAMESPACE" annotate cm "$name" grafana_folder=NoETL --overwrite >/dev/null 2>&1 || true
}

apply_cm noetl-dashboard-server "$SERVER_JSON"
apply_cm noetl-dashboard-workers "$WORKERS_JSON"

info "Dashboards provisioned. If Grafana is running, the sidecar should import them within ~30s."
info "Open Grafana: http://localhost:3000 (see credentials via 'make grafana-credentials')"
