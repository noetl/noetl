#!/usr/bin/env bash
set -euo pipefail

# Import NoETL dashboards into Grafana via HTTP API
# - Assumes Grafana is (or will be) port-forwarded to http://localhost:3000
# - Reads admin creds from vmstack-grafana Secret
# - Creates folder "NoETL" (uid: noetl) if missing, then imports dashboards
#
# Usage:
#   k8s/observability/import-dashboards.sh [NAMESPACE] [--wait] [--timeout=SECONDS]
#   (default namespace: observability)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
GRAFANA_URL="http://localhost:3000"

# Defaults
NAMESPACE="observability"
WAIT_MODE=false
TIMEOUT_SECS=180

# Simple args parsing
for arg in "$@"; do
  case "$arg" in
    --wait)
      WAIT_MODE=true
      ;;
    --timeout=*)
      TIMEOUT_SECS="${arg#*=}"
      ;;
    *)
      # treat the first non-flag as namespace
      if [ "$arg" != "${arg#-}" ]; then
        : # ignore unknown flags
      else
        NAMESPACE="$arg"
      fi
      ;;
  esac
done

DASH_DIR="${REPO_ROOT}/docs/observability/dashboards"
SERVER_JSON="${DASH_DIR}/noetl-server-dashboard.json"
WORKERS_JSON="${DASH_DIR}/noetl-workers-dashboard.json"

need_cmd() { command -v "$1" >/dev/null 2>&1; }
info() { echo "[INFO] $*"; }
warn() { echo "[WARN] $*"; }
err() { echo "[ERROR] $*" 1>&2; }

if ! need_cmd kubectl; then
  err "kubectl is not installed or not in PATH."; exit 2
fi
if ! need_cmd curl; then
  err "curl is required."; exit 2
fi

# Calculate retry counts based on timeout
# We'll dedicate up to half the timeout to waiting for credentials, and half to waiting for API reachability.
CREDS_BUDGET=$(( TIMEOUT_SECS / 2 ))
API_BUDGET=$(( TIMEOUT_SECS - CREDS_BUDGET ))
ATTEMPTS_CREDS=$(( CREDS_BUDGET / 2 ))
if [ "$ATTEMPTS_CREDS" -lt 1 ]; then ATTEMPTS_CREDS=1; fi
SLEEP_CREDS=2

# Get admin credentials via existing helper with retries (Grafana secret can take time to appear)
CREDS_OK=false
for i in $(seq 1 $ATTEMPTS_CREDS); do
  if CREDS_OUT="$(${SCRIPT_DIR}/grafana-credentials.sh "${NAMESPACE}" 2>/dev/null)"; then
    USER=$(echo "$CREDS_OUT" | awk -F': ' '/username:/ {print $2}' | tr -d '\r')
    PASS=$(echo "$CREDS_OUT" | awk -F': ' '/password:/ {print $2}' | tr -d '\r')
    if [ -n "$USER" ] && [ -n "$PASS" ]; then
      CREDS_OK=true
      break
    fi
  fi
  # If not waiting, don't loop too long – 20 attempts max as before
  if [ "$WAIT_MODE" != true ] && [ "$i" -ge 20 ]; then
    break
  fi
  sleep "$SLEEP_CREDS"
 done

if [ "$CREDS_OK" != true ]; then
  if [ "$WAIT_MODE" = true ]; then
    err "Timed out waiting for Grafana credentials in namespace '${NAMESPACE}' after ${CREDS_BUDGET}s."
    err "You can inspect secrets with: kubectl -n ${NAMESPACE} get secrets | grep grafana"
    exit 6
  else
    warn "Grafana credentials not available yet in namespace '${NAMESPACE}'."
    warn "Grafana may still be starting or the Secret 'vmstack-grafana' hasn't been created."
    warn "You can try again shortly or run: make observability-grafana-credentials"
    warn "Tip: To wait until Grafana is ready, run: make observability-import-dashboards (uses --wait)"
    warn "Skipping dashboard import for now (will not fail the build)."
    exit 0
  fi
fi

# Ensure Grafana is reachable; if not and WAIT_MODE, try to start port-forward and wait
ATTEMPTS=$(( API_BUDGET ))
if [ "$ATTEMPTS" -lt 5 ]; then ATTEMPTS=5; fi
SLEEP_SECS=1

check_api() {
  curl -sk --fail "${GRAFANA_URL}/api/health" >/dev/null 2>&1
}

if ! check_api; then
  if [ "$WAIT_MODE" = true ]; then
    warn "Grafana API not reachable at ${GRAFANA_URL}. Ensuring port-forward is running..."
    if [ -x "${SCRIPT_DIR}/port-forward.sh" ]; then
      "${SCRIPT_DIR}/port-forward.sh" start >/dev/null 2>&1 || true
    fi
  fi
fi

API_OK=false
for i in $(seq 1 $ATTEMPTS); do
  if check_api; then API_OK=true; break; fi
  sleep "$SLEEP_SECS"
 done

if [ "$API_OK" != true ]; then
  if [ "$WAIT_MODE" = true ]; then
    err "Grafana API still not reachable at ${GRAFANA_URL} after ${API_BUDGET}s."
    exit 4
  else
    err "Grafana API not reachable at ${GRAFANA_URL}. Start port-forwarding first or run with --wait."
    exit 4
  fi
fi

# Ensure NoETL folder exists (uid: noetl)
create_folder() {
  local title="$1"; local uid="$2"
  # Try to get folder by uid
  if curl -sk -u "$USER:$PASS" --fail "${GRAFANA_URL}/api/folders/$uid" >/dev/null 2>&1; then
    info "Grafana folder '$title' exists (uid=$uid)"
    return 0
  fi
  # Try to create
  if curl -sk -u "$USER:$PASS" -H 'Content-Type: application/json' -X POST \
    -d "{\"uid\":\"$uid\",\"title\":\"$title\"}" \
    "${GRAFANA_URL}/api/folders" >/dev/null 2>&1; then
    info "Created Grafana folder '$title' (uid=$uid)"
    return 0
  fi
  # If 409 conflict or other, we will proceed – fallback to root folder
  warn "Could not create/find folder '$title'. Dashboards will be imported into the General folder."
  return 1
}

FOLDER_UID="noetl"
FOLDER_CREATED=false
if create_folder "NoETL" "$FOLDER_UID"; then FOLDER_CREATED=true; fi

import_dashboard() {
  local file="$1"; local name="$2"
  if [ ! -f "$file" ]; then
    warn "Dashboard JSON not found: $file"; return 0
  fi
  # Ensure the dashboard JSON has "id": null for import semantics
  # Read file and force id=null in a minimal way using jq if available
  local body_json
  if need_cmd jq; then
    body_json=$(jq ' .id=null ' "$file")
  else
    # naive replace: if "id": appears, set to null; otherwise leave
    body_json=$(sed 's/"id"[[:space:]]*:[[:space:]]*[0-9]\+/"id": null/g' "$file")
  fi
  local payload
  # Map dashboard __inputs to our provisioned datasource names so panels query the right sources
  read -r -d '' INPUTS_JSON <<'JSON'
[
  { "name": "DS_PROMETHEUS", "type": "datasource", "pluginId": "prometheus", "value": "VictoriaMetrics" },
  { "name": "DS_VICTORIA_LOGS", "type": "datasource", "pluginId": "victorialogs-datasource", "value": "VictoriaLogs" }
]
JSON

  if [ "$FOLDER_CREATED" = true ]; then
    payload=$(cat <<EOF
{ "dashboard": $body_json, "overwrite": true, "folderUid": "$FOLDER_UID", "inputs": $INPUTS_JSON }
EOF
)
  else
    payload=$(cat <<EOF
{ "dashboard": $body_json, "overwrite": true, "inputs": $INPUTS_JSON }
EOF
)
  fi
  info "Importing dashboard: $name"
  if ! curl -sk -u "$USER:$PASS" -H 'Content-Type: application/json' -X POST \
    -d "$payload" "${GRAFANA_URL}/api/dashboards/db" >/dev/null 2>&1; then
    warn "Failed to import dashboard: $name"
  else
    info "Imported: $name"
  fi
}

import_dashboard "$SERVER_JSON" "NoETL Server Overview"
import_dashboard "$WORKERS_JSON" "NoETL Worker Pools"

info "Dashboard import completed. Check Grafana: ${GRAFANA_URL}/dashboards" 
