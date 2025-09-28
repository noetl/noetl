#!/usr/bin/env bash
set -euo pipefail

# Provision Grafana datasources via ConfigMap for the victoria-metrics-k8s-stack Grafana
# - Creates/updates a ConfigMap labeled grafana_datasource=1 so Grafana sidecar imports it
# - Defines two datasources: Prometheus (VictoriaMetrics vmsingle) and VictoriaLogs
# - Defaults to namespace 'observability' (pass different namespace as first arg)
#
# Usage:
#   k8s/observability/provision-datasources.sh [NAMESPACE]
#   (or via Makefile: make observability-provision-datasources)

NAMESPACE="${1:-observability}"

need_cmd() { command -v "$1" >/dev/null 2>&1; }
info() { echo "[INFO] $*"; }
warn() { echo "[WARN] $*"; }
err()  { echo "[ERROR] $*" 1>&2; }

if ! need_cmd kubectl; then
  err "kubectl is not installed or not in PATH."
  echo "Install kubectl: https://kubernetes.io/docs/tasks/tools/"
  exit 2
fi

# Ensure namespace exists
if ! kubectl get ns "$NAMESPACE" >/dev/null 2>&1; then
  err "Namespace '$NAMESPACE' not found. Run 'make observability-deploy' first."
  exit 3
fi

# Discover in-cluster service URLs (fallback to typical names)
VMSVC="vmstack-victoria-metrics-single"
if ! kubectl -n "$NAMESPACE" get svc "$VMSVC" >/dev/null 2>&1; then
  # Try alternative
  ALT=$(kubectl -n "$NAMESPACE" get svc -o name 2>/dev/null | grep -E '^service/(vmstack-victoria-metrics-|vmsingle-)' | head -n1 | sed 's#service/##' || true)
  if [ -n "$ALT" ]; then VMSVC="$ALT"; fi
fi
VM_URL="http://$VMSVC.$NAMESPACE.svc:8428"

VLOGSSVC="vlogs-victoria-logs-single"
if ! kubectl -n "$NAMESPACE" get svc "$VLOGSSVC" >/dev/null 2>&1; then
  ALT=$(kubectl -n "$NAMESPACE" get svc -o name 2>/dev/null | grep -E '^service/vlogs-' | head -n1 | sed 's#service/##' || true)
  if [ -n "$ALT" ]; then VLOGSSVC="$ALT"; fi
fi
VLOGS_URL="http://$VLOGSSVC.$NAMESPACE.svc:9428"

# Build the datasources YAML inline
# Using apiVersion 1 format consumed by grafana sidecar
read -r -d '' DATASOURCES <<YAML || true
apiVersion: 1

datasources:
  - name: VictoriaMetrics
    type: prometheus
    access: proxy
    url: ${VM_URL}
    isDefault: true
    jsonData:
      httpMethod: POST
    editable: true

  - name: VictoriaLogs
    type: victorialogs-datasource
    access: proxy
    url: ${VLOGS_URL}
    jsonData:
      # Default settings; adjust as needed
      timeout: 60
    editable: true
YAML

# Apply as a ConfigMap
CM_NAME="noetl-grafana-datasources"
info "Applying Grafana datasources ConfigMap '$CM_NAME' (namespace: $NAMESPACE)"

# Create or update the ConfigMap with the datasources.yaml key
kubectl -n "$NAMESPACE" create configmap "$CM_NAME" \
  --from-literal=datasources.yaml="${DATASOURCES}" \
  -o yaml --dry-run=client | kubectl apply -f -

# Label for Grafana sidecar to pick up datasources, searchNamespace=ALL is set in Helm flags
kubectl -n "$NAMESPACE" label cm "$CM_NAME" grafana_datasource=1 --overwrite >/dev/null 2>&1 || true

info "Grafana datasources provisioned:"
info "  - VictoriaMetrics (Prometheus): ${VM_URL}"
info "  - VictoriaLogs: ${VLOGS_URL}"
info "Grafana should load these within ~30s if running. If not, check the Grafana sidecar logs."
