#!/usr/bin/env bash
set -euo pipefail

# Deploy local observability stack (VictoriaMetrics + VictoriaLogs + Vector) into namespace 'observability'
# All Kubernetes-related deployment logic is kept within k8s/.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
NAMESPACE="observability"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    return 1
  fi
}

info() { echo "[INFO] $*"; }
warn() { echo "[WARN] $*"; }
error() { echo "[ERROR] $*" 1>&2; }

# Check required tools
if ! need_cmd kubectl; then
  error "kubectl is not installed or not in PATH. Skipping deployment."
  echo "\nInstall kubectl: https://kubernetes.io/docs/tasks/tools/"
  echo "Then re-run: make observability-deploy"
  exit 0
fi
if ! need_cmd helm; then
  error "helm is not installed or not in PATH. Skipping deployment."
  echo "\nInstall Helm (one of):"
  echo "  - macOS (Homebrew):   brew install helm"
  echo "  - Linux (script):     curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash"
  echo "  - Docs:               https://helm.sh/docs/intro/install/"
  echo "\nThen re-run: make observability-deploy"
  exit 0
fi

info "Deploying local observability stack to namespace '${NAMESPACE}'..."

# Add/update repos
helm repo add vm https://victoriametrics.github.io/helm-charts/ >/dev/null 2>&1 || true
helm repo add vector https://helm.vector.dev >/dev/null 2>&1 || true
helm repo update

# Ensure namespace exists
if ! kubectl get ns "${NAMESPACE}" >/dev/null 2>&1; then
  info "Creating namespace ${NAMESPACE}"
  kubectl create ns "${NAMESPACE}"
fi

# VictoriaMetrics stack (Grafana + vmagent + vmsingle)
info "Installing/Upgrading VictoriaMetrics k8s stack (vmstack)"
VMSTACK_VALUES="${SCRIPT_DIR}/vmstack-values.yaml"
if [ -f "${VMSTACK_VALUES}" ]; then
  info "Using custom vmstack values (${VMSTACK_VALUES})"
  helm upgrade --install vmstack vm/victoria-metrics-k8s-stack -n "${NAMESPACE}" \
    -f "${VMSTACK_VALUES}" \
    --set grafana.enabled=true \
    --set grafana.sidecar.dashboards.enabled=true \
    --set grafana.sidecar.dashboards.label=grafana_dashboard \
    --set-string grafana.sidecar.dashboards.labelValue=1 \
    --set grafana.sidecar.dashboards.searchNamespace=ALL \
    --set grafana.sidecar.dashboards.folderAnnotation=grafana_folder \
    --set-string grafana.sidecar.dashboards.defaultFolderName=NoETL \
    --set grafana.sidecar.datasources.enabled=true \
    --set grafana.sidecar.datasources.label=grafana_datasource \
    --set grafana.sidecar.datasources.searchNamespace=ALL \
    --set vmsingle.enabled=true \
    --set vmsingle.spec.retentionPeriod=1w \
    --set vmagent.enabled=true
else
  helm upgrade --install vmstack vm/victoria-metrics-k8s-stack -n "${NAMESPACE}" \
    --set grafana.enabled=true \
    --set grafana.sidecar.dashboards.enabled=true \
    --set grafana.sidecar.dashboards.label=grafana_dashboard \
    --set-string grafana.sidecar.dashboards.labelValue=1 \
    --set grafana.sidecar.dashboards.searchNamespace=ALL \
    --set grafana.sidecar.dashboards.folderAnnotation=grafana_folder \
    --set-string grafana.sidecar.dashboards.defaultFolderName=NoETL \
    --set grafana.sidecar.datasources.enabled=true \
    --set grafana.sidecar.datasources.label=grafana_datasource \
    --set grafana.sidecar.datasources.searchNamespace=ALL \
    --set vmsingle.enabled=true \
    --set vmsingle.spec.retentionPeriod=1w \
    --set vmagent.enabled=true
fi

# Wait for operator webhook to become ready before applying CRDs referencing it
info "Waiting for VictoriaMetrics operator deployment to become ready"
if ! kubectl rollout status deployment/vmstack-victoria-metrics-operator -n "${NAMESPACE}" --timeout=180s >/dev/null 2>&1; then
  warn "VictoriaMetrics operator deployment not ready after timeout; continuing but webhook operations may fail"
else
  sleep 3
fi

# VictoriaLogs single node
info "Installing/Upgrading VictoriaLogs (vlogs)"
helm upgrade --install vlogs vm/victoria-logs-single -n "${NAMESPACE}"

# Vector DaemonSet: prefer our values if present
VECTOR_VALUES="${SCRIPT_DIR}/vector-values.yaml"
if [ -f "${VECTOR_VALUES}" ]; then
  info "Installing/Upgrading Vector with custom values (${VECTOR_VALUES})"
  helm upgrade --install vector vector/vector -n "${NAMESPACE}" -f "${VECTOR_VALUES}"
else
  warn "${VECTOR_VALUES} not found; installing Vector with default Agent role"
  helm upgrade --install vector vector/vector -n "${NAMESPACE}" --set role=Agent --set service.enabled=false
fi

# Apply VMPodScrape so vmagent scrapes the NoETL server metrics
VMPODSCRAPE_MANIFEST="${SCRIPT_DIR}/vmpodscrape-noetl.yaml"
if [ -f "${VMPODSCRAPE_MANIFEST}" ]; then
  info "Ensuring VictoriaMetrics CRD for VMPodScrape is available"
  if ! kubectl get crd vmpodscrapes.operator.victoriametrics.com >/dev/null 2>&1; then
    info "Waiting for vmpodscrapes.operator.victoriametrics.com CRD to be created..."
    for attempt in $(seq 1 30); do
      if kubectl get crd vmpodscrapes.operator.victoriametrics.com >/dev/null 2>&1; then
        break
      fi
      sleep 2
    done
  fi
  if kubectl get crd vmpodscrapes.operator.victoriametrics.com >/dev/null 2>&1; then
    info "Applying VMPodScrape manifest ${VMPODSCRAPE_MANIFEST}"
    kubectl apply -f "${VMPODSCRAPE_MANIFEST}"
  else
    warn "vmpodscrapes.operator.victoriametrics.com CRD not available; skipping VMPodScrape application"
  fi
else
  warn "${VMPODSCRAPE_MANIFEST} not found; skipping VMPodScrape application"
fi

# Provision Grafana dashboards (NoETL server & workers) via ConfigMaps (sidecar)
"${SCRIPT_DIR}/provision-grafana.sh" "${NAMESPACE}" || true

# Provision Grafana datasources (VictoriaMetrics + VictoriaLogs) via ConfigMap (sidecar)
"${SCRIPT_DIR}/provision-datasources.sh" "${NAMESPACE}" || true

# Automatically start port-forwarding for UIs in the background
"${SCRIPT_DIR}/port-forward.sh" start || true

# Fallback/import: also push dashboards via Grafana HTTP API (ensures they appear even if sidecar misses them)
# This requires the port-forward to be active and Grafana Secret available; runs best-effort.
"${SCRIPT_DIR}/import-dashboards.sh" "${NAMESPACE}" || true

cat <<EOF

Observability stack deployed.

Port-forwarding for UIs has been started in the background. Open:
  - Grafana:            http://localhost:3000
  - VictoriaLogs UI:    http://localhost:9428
  - VictoriaMetrics UI: http://localhost:8428/vmui/

Get Grafana credentials:
  - Makefile target:    make observability-grafana-credentials
  - Script:             ${SCRIPT_DIR}/grafana-credentials.sh observability

Manage port-forwarding:
  - Status: ${SCRIPT_DIR}/port-forward.sh status
  - Stop:   ${SCRIPT_DIR}/port-forward.sh stop
  - Start:  ${SCRIPT_DIR}/port-forward.sh start

Tip: In Grafana, add VictoriaMetrics and VictoriaLogs datasources if they are not preloaded.
EOF
