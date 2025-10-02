#!/usr/bin/env bash
set -euo pipefail

# Print Grafana admin credentials from the vmstack-grafana Secret
# Defaults: namespace=observability, secret=vmstack-grafana
# Usage:
#   k8s/observability/grafana-credentials.sh [NAMESPACE]
#   (or via Makefile: make observability-grafana-credentials)

NAMESPACE="${1:-observability}"
SECRET_NAME="vmstack-grafana"

need_cmd() { command -v "$1" >/dev/null 2>&1; }
info() { echo "[INFO] $*"; }
err() { echo "[ERROR] $*" 1>&2; }

if ! need_cmd kubectl; then
  err "kubectl is not installed or not in PATH."
  echo "Install kubectl: https://kubernetes.io/docs/tasks/tools/"
  exit 2
fi

# Check namespace exists
if ! kubectl get ns "$NAMESPACE" >/dev/null 2>&1; then
  err "Namespace '$NAMESPACE' not found."
  echo "Hint: If you used make unified-deploy, the namespace should be 'noetl-platform'."
  exit 3
fi

# Check secret exists
if ! kubectl -n "$NAMESPACE" get secret "$SECRET_NAME" >/dev/null 2>&1; then
  err "Secret '$SECRET_NAME' not found in namespace '$NAMESPACE'."
  echo "It may take a few seconds after Grafana starts for the secret to appear."
  echo "Try again shortly, or list secrets: kubectl -n $NAMESPACE get secrets | grep grafana"
  exit 4
fi

USER=$(kubectl -n "$NAMESPACE" get secret "$SECRET_NAME" -o jsonpath='{.data.admin-user}' | base64 --decode || true)
PASS=$(kubectl -n "$NAMESPACE" get secret "$SECRET_NAME" -o jsonpath='{.data.admin-password}' | base64 --decode || true)

if [ -z "$USER" ] || [ -z "$PASS" ]; then
  err "Failed to decode Grafana credentials from secret '$SECRET_NAME' in '$NAMESPACE'."
  echo "Secret data keys expected: admin-user, admin-password"
  exit 5
fi

cat <<EOF
Grafana credentials (namespace: $NAMESPACE):
  username: $USER
  password: $PASS

Open Grafana at: http://localhost:3000
EOF
