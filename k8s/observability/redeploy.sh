#!/usr/bin/env bash
set -euo pipefail

# Redeploy the local observability stack by uninstalling Helm releases and re-installing.
# Keeps all logic under k8s/.
#
# Steps:
#  - Stop port-forwards
#  - Uninstall Helm releases: vmstack (VictoriaMetrics stack), vlogs (VictoriaLogs), vector (Vector)
#  - Clean Grafana dashboard ConfigMaps created by provisioning (label grafana_dashboard=1)
#  - Re-run deploy.sh
#
# Usage:
#   k8s/observability/redeploy.sh
#   (or via Makefile: make observability-redeploy)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="observability"

need_cmd() { command -v "$1" >/dev/null 2>&1; }
info() { echo "[INFO] $*"; }
warn() { echo "[WARN] $*"; }
err()  { echo "[ERROR] $*" 1>&2; }

# Tool checks (graceful skip like deploy.sh)
if ! need_cmd kubectl; then
  err "kubectl is not installed or not in PATH. Skipping redeploy."
  echo "\nInstall kubectl: https://kubernetes.io/docs/tasks/tools/"
  echo "Then re-run: make observability-redeploy"
  exit 0
fi
if ! need_cmd helm; then
  err "helm is not installed or not in PATH. Skipping redeploy."
  echo "\nInstall Helm (one of):"
  echo "  - macOS (Homebrew):   brew install helm"
  echo "  - Linux (script):     curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash"
  echo "  - Docs:               https://helm.sh/docs/intro/install/"
  echo "\nThen re-run: make observability-redeploy"
  exit 0
fi

info "Stopping background port-forwards (if any)"
"${SCRIPT_DIR}/port-forward.sh" stop || true

# If namespace doesn't exist, just deploy fresh
if ! kubectl get ns "${NAMESPACE}" >/dev/null 2>&1; then
  warn "Namespace '${NAMESPACE}' not found. Performing fresh deploy instead."
  exec "${SCRIPT_DIR}/deploy.sh"
fi

info "Uninstalling Helm releases in namespace '${NAMESPACE}' (if installed)"
set +e
helm -n "${NAMESPACE}" uninstall vector >/dev/null 2>&1
helm -n "${NAMESPACE}" uninstall vlogs >/dev/null 2>&1
helm -n "${NAMESPACE}" uninstall vmstack >/dev/null 2>&1
set -e

# Clean up provisioned dashboard ConfigMaps; ignore errors if none
info "Cleaning Grafana dashboard ConfigMaps (label grafana_dashboard=1)"
set +e
for cm in $(kubectl -n "${NAMESPACE}" get cm -l grafana_dashboard=1 -o name 2>/dev/null); do
  kubectl -n "${NAMESPACE}" delete "$cm" >/dev/null 2>&1 || true
done
set -e

info "Waiting briefly for resources to terminate..."
sleep 3

info "Re-deploying the observability stack"
"${SCRIPT_DIR}/deploy.sh"
