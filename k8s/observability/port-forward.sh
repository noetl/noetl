#!/usr/bin/env bash
set -euo pipefail

# Manage port-forwarding for the local observability stack UIs
# Services:
#  - Grafana:            svc/vmstack-grafana                 -> localhost:3000
#  - VictoriaLogs UI:    svc/vlogs-victoria-logs-single      -> localhost:9428
#  - VictoriaMetrics UI: svc/vmstack-victoria-metrics-single -> localhost:8428
#
# Usage:
#   k8s/observability/port-forward.sh start   # start background port-forwards
#   k8s/observability/port-forward.sh stop    # stop background port-forwards
#   k8s/observability/port-forward.sh status  # show status

NAMESPACE="noetl-platform"
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PF_DIR="${BASE_DIR}/.pf"
LOG_GRAFANA="${BASE_DIR}/port-forward-grafana.log"
LOG_VLOGS="${BASE_DIR}/port-forward-victorialogs.log"
LOG_VMUI="${BASE_DIR}/port-forward-victoriametrics.log"
PID_GRAFANA="${PF_DIR}/grafana.pid"
PID_VLOGS="${PF_DIR}/victorialogs.pid"
PID_VMUI="${PF_DIR}/victoriametrics.pid"

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

echo_info() { echo "[INFO] $*"; }
echo_warn() { echo "[WARN] $*"; }
echo_err() { echo "[ERROR] $*" 1>&2; }

ensure_tools() {
  if ! need_cmd kubectl; then
    echo_err "kubectl not found in PATH"
    echo "Install kubectl: https://kubernetes.io/docs/tasks/tools/"; exit 1
  fi
}

is_running() {
  local pid_file="$1"
  if [ -f "$pid_file" ]; then
    local pid
    pid=$(cat "$pid_file" || true)
    if [ -n "${pid}" ] && ps -p "$pid" >/dev/null 2>&1; then
      return 0
    fi
  fi
  return 1
}

start_pf() {
  local desc="$1"; shift
  local pid_file="$1"; shift
  local log_file="$1"; shift
  # Remaining args form the kubectl command
  if is_running "$pid_file"; then
    echo_info "$desc port-forward already running (PID: $(cat "$pid_file"))"
    return 0
  fi
  # Ensure log directory exists
  mkdir -p "$(dirname "$log_file")" "$PF_DIR"
  # Start in background
  nohup "$@" >"$log_file" 2>&1 &
  local pid=$!
  echo "$pid" > "$pid_file"
  echo_info "Started $desc port-forward (PID: $pid). Logs: $log_file"
}

stop_pf() {
  local desc="$1"; shift
  local pid_file="$1"; shift
  if is_running "$pid_file"; then
    local pid
    pid=$(cat "$pid_file")
    kill "$pid" >/dev/null 2>&1 || true
    # Wait briefly and force kill if needed
    sleep 0.5
    if ps -p "$pid" >/dev/null 2>&1; then
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
    rm -f "$pid_file"
    echo_info "Stopped $desc port-forward (PID: $pid)"
  else
    echo_info "$desc port-forward not running"
  fi
}

status_pf() {
  local desc="$1"; shift
  local pid_file="$1"; shift
  if is_running "$pid_file"; then
    echo_info "$desc: running (PID: $(cat "$pid_file"))"
  else
    echo_info "$desc: not running"
  fi
}

# Resolve VictoriaLogs service name dynamically
get_vlogs_svc() {
  local candidates=(
    "vlogs-victoria-logs-single"
    "vlogs-victoria-logs-single-server"
  )
  for name in "${candidates[@]}"; do
    if kubectl -n "$NAMESPACE" get svc "$name" >/dev/null 2>&1; then
      echo "$name"; return 0
    fi
  done
  # Fallback: try to discover by regex
  kubectl -n "$NAMESPACE" get svc -o name 2>/dev/null | grep -Eo 'vlogs-[^/ ]+' | head -n1 | sed 's#service/##' || true
}

# Resolve VictoriaMetrics vmsingle service name dynamically
get_vmui_svc() {
  local candidates=(
    "vmstack-victoria-metrics-single"
    "vmstack-victoria-metrics-vmsingle"
  )
  for name in "${candidates[@]}"; do
    if kubectl -n "$NAMESPACE" get svc "$name" >/dev/null 2>&1; then
      echo "$name"; return 0
    fi
  done

  # Prefer services that start with vmsingle-
  local by_prefix
  by_prefix=$(kubectl -n "$NAMESPACE" get svc -o name 2>/dev/null | grep -E '^service/vmsingle-' | head -n1 | sed 's#service/##' || true)
  if [ -n "$by_prefix" ]; then
    echo "$by_prefix"; return 0
  fi

  # Try label-based discovery for the Service (prefer vmsingle)
  local by_label_vmsingle
  by_label_vmsingle=$(kubectl -n "$NAMESPACE" get svc -l app.kubernetes.io/instance=vmstack -o name 2>/dev/null | grep -Ei 'vmsingle' | head -n1 | sed 's#service/##' || true)
  if [ -n "$by_label_vmsingle" ]; then
    echo "$by_label_vmsingle"; return 0
  fi

  # Fallbacks: general regex, prioritizing vmsingle and avoiding vmagent
  local fallback_vmsingle
  fallback_vmsingle=$(kubectl -n "$NAMESPACE" get svc -o name 2>/dev/null | grep -Ei 'vmsingle' | head -n1 | sed 's#service/##' || true)
  if [ -n "$fallback_vmsingle" ]; then
    echo "$fallback_vmsingle"; return 0
  fi

  kubectl -n "$NAMESPACE" get svc -o name 2>/dev/null | grep -Ei 'victoria.*metrics' | grep -Ev 'vmagent' | head -n1 | sed 's#service/##' || true
}

# Resolve a vmsingle Pod if Service is not discoverable
get_vmui_pod() {
  # Prefer label-based selection
  local pod
  pod=$(kubectl -n "$NAMESPACE" get pod \
    -l app.kubernetes.io/component=vmsingle \
    -o name 2>/dev/null | head -n1 | sed 's#pod/##' || true)
  if [ -n "$pod" ]; then
    echo "$pod"; return 0
  fi
  # Fallback: grep by name
  kubectl -n "$NAMESPACE" get pod -o name 2>/dev/null | grep -Ei 'victoria.*(metrics|single|vmsingle)' | head -n1 | sed 's#pod/##' || true
}

start_all() {
  ensure_tools
  # Resolve services
  local vlogs_svc; vlogs_svc="$(get_vlogs_svc)" || vlogs_svc=""
  local vmui_svc; vmui_svc="$(get_vmui_svc)" || vmui_svc=""
  local vmui_pod; vmui_pod=""

  # Start Grafana 3000:80
  start_pf "Grafana" "$PID_GRAFANA" "$LOG_GRAFANA" \
    kubectl -n "$NAMESPACE" port-forward svc/vmstack-grafana 3000:80

  # Start VictoriaLogs 9428:9428 (if service found)
  if [ -n "$vlogs_svc" ]; then
    start_pf "VictoriaLogs" "$PID_VLOGS" "$LOG_VLOGS" \
      kubectl -n "$NAMESPACE" port-forward svc/"$vlogs_svc" 9428:9428
  else
    echo_warn "Could not find VictoriaLogs Service in namespace '$NAMESPACE'. Skipping port-forward for VictoriaLogs."
  fi

  # Start VictoriaMetrics UI 8428:8428 with retries (Service preferred, fallback to Pod)
  started=false
  if [ -n "$vmui_svc" ]; then
    for attempt in 1 2 3; do
      start_pf "VictoriaMetrics UI" "$PID_VMUI" "$LOG_VMUI" \
        kubectl -n "$NAMESPACE" port-forward svc/"$vmui_svc" 8428:8428
      sleep 2
      if is_running "$PID_VMUI"; then
        started=true
        break
      else
        # Clean up any stale PID and retry
        stop_pf "VictoriaMetrics UI" "$PID_VMUI"
        echo_warn "Retry $attempt/3 for VictoriaMetrics UI via Service '$vmui_svc' failed; retrying..."
      fi
    done
  fi

  if [ "$started" != true ]; then
    vmui_pod="$(get_vmui_pod)" || vmui_pod=""
    if [ -n "$vmui_pod" ]; then
      for attempt in 1 2 3; do
        start_pf "VictoriaMetrics UI" "$PID_VMUI" "$LOG_VMUI" \
          kubectl -n "$NAMESPACE" port-forward pod/"$vmui_pod" 8428:8428
        sleep 2
        if is_running "$PID_VMUI"; then
          started=true
          break
        else
          stop_pf "VictoriaMetrics UI" "$PID_VMUI"
          echo_warn "Retry $attempt/3 for VictoriaMetrics UI via Pod '$vmui_pod' failed; retrying..."
        fi
      done
    fi
  fi

  if [ "$started" != true ]; then
    echo_warn "Could not start VictoriaMetrics UI port-forward (svc or pod) in namespace '$NAMESPACE'."
    echo_warn "Hint: Services in namespace:"
    kubectl -n "$NAMESPACE" get svc | sed 's/^/[WARN]   /'
  fi

  echo
  echo "Port-forwards active (where available). Open the UIs:"
  echo "  - Grafana:            http://localhost:3000"
  echo "  - VictoriaLogs UI:    http://localhost:9428"
  echo "  - VictoriaMetrics UI: http://localhost:8428/vmui/"
  echo
  echo "To stop: $0 stop"
}

stop_all() {
  stop_pf "Grafana" "$PID_GRAFANA"
  stop_pf "VictoriaLogs" "$PID_VLOGS"
  stop_pf "VictoriaMetrics UI" "$PID_VMUI"
}

status_all() {
  status_pf "Grafana" "$PID_GRAFANA"
  status_pf "VictoriaLogs" "$PID_VLOGS"
  status_pf "VictoriaMetrics UI" "$PID_VMUI"
}

cmd="${1:-start}"
case "$cmd" in
  start)
    start_all
    ;;
  stop)
    stop_all
    ;;
  status)
    status_all
    ;;
  *)
    echo "Usage: $0 {start|stop|status}"; exit 1
    ;;
 esac
