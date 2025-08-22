# bash
#!/usr/bin/env bash
# File: bin/dev_detach.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

LOG_DIR="logs"
PID_DIR="$LOG_DIR"
mkdir -p "$LOG_DIR" "$PID_DIR"

export PYTHONUNBUFFERED=1
export NO_COLOR=1

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env >/dev/null 2>&1 || true
  set +a
fi

resolve_uvicorn_target() {
  if [[ -n "${UVICORN_APP:-}" ]]; then
    echo "$UVICORN_APP"
    return 0
  fi
  local candidates=(
    "noetl.app:app"
    "noetl.api:app"
    "noetl.server:app"
    "noetl.server_api:app"
    "noetl.main:app"
    "noetl.web:app"
  )
  for t in "${candidates[@]}"; do
    if python - "$t" >/dev/null 2>&1 <<'PY'
import importlib, sys
target = sys.argv[1]
mod, attr = target.split(":")
m = importlib.import_module(mod)
getattr(m, attr)
PY
    then
      echo "$t"
      return 0
    fi
  done
  return 1
}

module_exists() {
  python - "$1" >/dev/null 2>&1 <<'PY'
import importlib, sys
importlib.import_module(sys.argv[1])
PY
}

has_attr() {
  local module="$1" attr="${2:-app}"
  python - "$module" "$attr" >/dev/null 2>&1 <<'PY'
import importlib, sys
m = importlib.import_module(sys.argv[1])
getattr(m, sys.argv[2])
PY
}

best_entry_cmd() {
  local pkg="$1"
  local cmd
  if ! cmd="$(python - "$pkg" <<'PY'
import importlib, importlib.util, sys
pkg = sys.argv[1]

def has_dunder_main(p):
    return importlib.util.find_spec(p + ".__main__") is not None

def find_callable(mod_name, names=("main","run","serve","cli","start","worker","broker")):
    try:
        m = importlib.import_module(mod_name)
    except Exception:
        return None
    for n in names:
        f = getattr(m, n, None)
        if callable(f):
            return f"from {mod_name} import {n} as _f; _f()"
    return None

if has_dunder_main(pkg):
    print(f"python -m {pkg}")
    sys.exit(0)

code = find_callable(pkg + ".main")
if code:
    print(f"python -c '{code}'")
    sys.exit(0)

code = find_callable(pkg)
if code:
    print(f"python -c '{code}'")
    sys.exit(0)

sys.exit(2)
PY
)"; then
    return 1
  fi
  printf '%s\n' "$cmd"
}

# Check if a TCP port is in use on a given host.
port_in_use() {
  local host="$1" port="$2"
  python - "$host" "$port" >/dev/null 2>&1 <<'PY'
import socket, sys
h, p = sys.argv[1], int(sys.argv[2])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(0.2)
try:
    if s.connect_ex((h, p)) == 0:
        sys.exit(0)
    else:
        sys.exit(1)
finally:
    s.close()
PY
}

# Try to find a PID listening on a given TCP port.
# Returns 0 and prints the PID on stdout if found; otherwise returns non-zero.
find_pid_by_port() {
  local port="$1"
  # Prefer lsof in LISTEN state (works on macOS and Linux with lsof installed)
  if command -v lsof >/dev/null 2>&1; then
    # -t for terse PIDs; -iTCP:port; -sTCP:LISTEN to restrict to listeners
    local pid
    pid="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -n1 || true)"
    if [[ -n "$pid" ]]; then
      echo "$pid"
      return 0
    fi
    # Fallback: broader lsof query (may include clients); still better than nothing
    pid="$(lsof -nP -iTCP:"$port" 2>/dev/null | awk 'NR>1 {print $2}' | head -n1 || true)"
    if [[ -n "$pid" ]]; then
      echo "$pid"
      return 0
    fi
  fi
  # Linux-only fallback via ss or netstat
  if command -v ss >/dev/null 2>&1; then
    local pid
    pid="$(ss -lptn "sport = :$port" 2>/dev/null | awk -F',' '/pid=/ {sub(/pid=/, "", $2); gsub(/\)/, "", $2); print $2; exit}')"
    if [[ -n "$pid" ]]; then
      echo "$pid"
      return 0
    fi
  fi
  if command -v netstat >/dev/null 2>&1; then
    # netstat output differs; try to extract PID/Program name on Linux
    local pid
    pid="$(netstat -lpn 2>/dev/null | awk -v p=":$port" '$4 ~ p {print $7}' | head -n1 | awk -F'/' '{print $1}')"
    if [[ -n "$pid" && "$pid" != "-" ]]; then
      echo "$pid"
      return 0
    fi
  fi
  return 1
}

start_service() {
  local name="$1" command="$2" logfile="$3" pidfile="$4"
  : > "$logfile"
  echo "Starting $name -> $logfile"
  nohup bash -c "source .env >/dev/null 2>&1 || true; exec $command" >>"$logfile" 2>&1 &
  local pid=$!
  echo "$pid" > "$pidfile"
  # Detect immediate crash and surface a clear message.
  sleep 0.3
  if ! kill -0 "$pid" 2>/dev/null; then
    # Special-case: if the service failed because the port is already in use, treat as non-fatal.
    if grep -qi "Address already in use" "$logfile" 2>/dev/null; then
      echo "$name did not start because the port is already in use. Assuming another instance is running. See $logfile"
      rm -f "$pidfile"
      return 0
    fi
    echo "Failed to start $name (exited immediately). See $logfile"
    rm -f "$pidfile"
    return 1
  fi
  echo "Started $name (pid=$pid)"
}

stop_service() {
  local name="$1" pidfile="$2"
  if [[ -f "$pidfile" ]]; then
    local pid; pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
      echo "Stopping $name (pid=$pid)"
      pkill -TERM -P "$pid" 2>/dev/null || true
      kill -TERM "$pid" 2>/dev/null || true
      sleep 1
      pkill -KILL -P "$pid" 2>/dev/null || true
      kill -KILL "$pid" 2>/dev/null || true
    else
      echo "Stopping $name: not running (stale pid=$pid), cleaning up pidfile"
    fi
    rm -f "$pidfile"
  else
    echo "$name not running (no pidfile)."
  fi
}

status_service() {
  local name="$1" pidfile="$2"
  if [[ -f "$pidfile" ]]; then
    local pid; pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
      echo "$name: running (pid=$pid)"
    else
      echo "$name: not running (stale pidfile=$pidfile)"
    fi
  else
    echo "$name: not running"
  fi
}

# Display port status with expected host/port
status_port() {
  local label="$1" host="$2" port="$3"
  local chk_host="$host"
  if [[ "$chk_host" == "0.0.0.0" || "$chk_host" == "*" ]]; then
    chk_host="127.0.0.1"
  fi
  if port_in_use "$chk_host" "$port"; then
    echo "$label: $host:$port -> LISTENING"
  else
    echo "$label: $host:$port -> not listening"
  fi
}

# Kill any running tailers and remove their pidfiles
kill_tailers() {
  # Kill by recorded PIDs first (best effort)
  for f in "$PID_DIR/tail.pid" "$PID_DIR/tail_server.pid" "$PID_DIR/tail_broker.pid" "$PID_DIR/tail_worker.pid" "$PID_DIR/tail_worker2.pid"; do
    if [[ -f "$f" ]]; then
      pid="$(cat "$f" 2>/dev/null || true)"
      if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        kill -TERM "$pid" 2>/dev/null || true
      fi
      rm -f "$f" 2>/dev/null || true
    fi
  done
  # Fallbacks: kill any tail readers on our logs (pattern-scoped)
  pkill -f "tail -n \+1 -F $LOG_DIR/server.log" 2>/dev/null || true
  pkill -f "tail -n \+1 -F $LOG_DIR/broker.log" 2>/dev/null || true
  pkill -f "tail -n \+1 -F $LOG_DIR/worker.log" 2>/dev/null || true
  pkill -f "tail -n \+1 -F $LOG_DIR/worker2.log" 2>/dev/null || true
  # More general patterns (in case shell condensed args differently)
  pkill -f "tail .* -F .*$LOG_DIR/server.log" 2>/dev/null || true
  pkill -f "tail .* -F .*$LOG_DIR/broker.log" 2>/dev/null || true
  pkill -f "tail .* -F .*$LOG_DIR/worker.log" 2>/dev/null || true
  pkill -f "tail .* -F .*$LOG_DIR/worker2.log" 2>/dev/null || true
}

tail_all() {
  touch "$LOG_DIR/server.log" "$LOG_DIR/broker.log" "$LOG_DIR/worker.log" "$LOG_DIR/worker2.log"

  # Prevent multiple concurrent tail sessions
  if [[ -f "$PID_DIR/tail.pid" ]]; then
    tpid="$(cat "$PID_DIR/tail.pid" 2>/dev/null || true)"
    if [[ -n "$tpid" ]] && kill -0 "$tpid" 2>/dev/null; then
      echo "A tail session is already running (pid=$tpid). Use: $0 tail-stop"
      return 1
    else
      rm -f "$PID_DIR/tail.pid" 2>/dev/null || true
    fi
  fi

  # Optional filter to reduce poll noise
  local server_tail="cat"
  local broker_tail="cat"
  if [[ "${NOETL_TAIL_FILTER_POLL:-false}" =~ ^(1|true|yes|on)$ ]]; then
    server_tail="grep -v -E 'GET /api/events(\?| )' || true"
    broker_tail="grep -v 'BrokerLoop: poll' || true"
  fi

  # Start tails in background
  bash -c "tail -n +1 -F '$LOG_DIR/server.log' | $server_tail | awk '{ print \"[server] \" \$0 }'" &
  p1=$!
  echo "$p1" > "$PID_DIR/tail_server.pid"
  bash -c "tail -n +1 -F '$LOG_DIR/broker.log' | $broker_tail | awk '{ print \"[broker] \" \$0 }'" &
  p2=$!
  echo "$p2" > "$PID_DIR/tail_broker.pid"
  bash -c "tail -n +1 -F '$LOG_DIR/worker.log' | awk '{ print \"[worker] \" \$0 }'" &
  p3=$!
  echo "$p3" > "$PID_DIR/tail_worker.pid"
  bash -c "tail -n +1 -F '$LOG_DIR/worker2.log' | awk '{ print \"[worker2] \" \$0 }'" &
  p4=$!
  echo "$p4" > "$PID_DIR/tail_worker2.pid"
  echo "$$" > "$PID_DIR/tail.pid"

  # Robust cleanup on multiple signals and normal exit
  trap 'kill_tailers; exit 0' INT TERM HUP EXIT

  echo "Tailing all logs. Ctrl+C to exit."
  wait $p1 $p2 $p3 $p4
}

cmd="${1:-}"
case "$cmd" in
  start)
    # Proactive port check for server
    SERVER_HOST_VAL="${NOETL_HOST:-0.0.0.0}"
    SERVER_PORT_VAL="${NOETL_PORT:-8082}"
    SERVER_CHECK_HOST="$SERVER_HOST_VAL"; [[ "$SERVER_CHECK_HOST" == "0.0.0.0" ]] && SERVER_CHECK_HOST="127.0.0.1"

    if port_in_use "$SERVER_CHECK_HOST" "$SERVER_PORT_VAL"; then
      echo "server-api-dev did not start because the port is already in use. Assuming another instance is running. See $LOG_DIR/server.log"
      # Attempt to capture PID of the existing server and write pidfile for management
      if pid=$(find_pid_by_port "$SERVER_PORT_VAL"); then
        echo "$pid" > "$PID_DIR/server.pid"
        echo "server-api-dev: captured existing PID $pid listening on port $SERVER_PORT_VAL"
      fi
    elif [[ -n "${SERVER_CMD:-}" ]]; then
      start_service "server-api-dev" "$SERVER_CMD" "$LOG_DIR/server.log" "$PID_DIR/server.pid"
    else
      start_service "server-api-dev" "make run-server-api-dev" "$LOG_DIR/server.log" "$PID_DIR/server.pid"
    fi

    # Broker: explicit BROKER_CMD > uvicorn noetl.broker:app (if app exists) > best_entry_cmd > fallback target.
    if [[ -n "${BROKER_CMD:-}" ]]; then
      start_service "broker" "$BROKER_CMD" "$LOG_DIR/broker.log" "$PID_DIR/broker.pid"
    elif has_attr "noetl.broker" "app"; then
      start_service "broker" "python -m uvicorn noetl.broker:app --host 0.0.0.0 --port ${BROKER_PORT:-8090} --reload" "$LOG_DIR/broker.log" "$PID_DIR/broker.pid"
    elif cmd=$(best_entry_cmd noetl.broker); then
      start_service "broker" "$cmd" "$LOG_DIR/broker.log" "$PID_DIR/broker.pid"
    else
      echo "No broker entrypoint found; falling back to 'make run-broker' (override with BROKER_CMD)."
      start_service "broker" "make run-broker" "$LOG_DIR/broker.log" "$PID_DIR/broker.pid"
    fi

    # Worker (primary)
    WORKER_HOST_VAL="${NOETL_WORKER_HOST:-0.0.0.0}"
    WORKER_PORT_VAL="${NOETL_WORKER_PORT:-8081}"
    WORKER_CHECK_HOST="$WORKER_HOST_VAL"; [[ "$WORKER_CHECK_HOST" == "0.0.0.0" ]] && WORKER_CHECK_HOST="127.0.0.1"

    if port_in_use "$WORKER_CHECK_HOST" "$WORKER_PORT_VAL"; then
      echo "worker-api-dev did not start because the port is already in use. Assuming another instance is running. See $LOG_DIR/worker.log"
      if pid=$(find_pid_by_port "$WORKER_PORT_VAL"); then
        echo "$pid" > "$PID_DIR/worker.pid"
        echo "worker-api-dev: captured existing PID $pid listening on port $WORKER_PORT_VAL"
      fi
    elif [[ -n "${WORKER_CMD:-}" ]]; then
      start_service "worker-api-dev" "$WORKER_CMD" "$LOG_DIR/worker.log" "$PID_DIR/worker.pid"
    elif has_attr "noetl.worker" "app"; then
      start_service "worker-api-dev" "python -m uvicorn noetl.worker:app --host 0.0.0.0 --port ${WORKER_PORT:-8081} --reload" "$LOG_DIR/worker.log" "$PID_DIR/worker.pid"
    elif cmd=$(best_entry_cmd noetl.worker); then
      start_service "worker-api-dev" "$cmd" "$LOG_DIR/worker.log" "$PID_DIR/worker.pid"
    else
      echo "No worker entrypoint found; falling back to 'make run-worker-api-dev' (override with WORKER_CMD)."
      start_service "worker-api-dev" "make run-worker-api-dev" "$LOG_DIR/worker.log" "$PID_DIR/worker.pid"
    fi

    # Optional Worker2 (e.g., GPU) if enabled
    if [[ "${NOETL_WORKER2_ENABLE:-false}" =~ ^(1|true|yes|on)$ ]]; then
      local W2_HOST="${NOETL_WORKER2_HOST:-0.0.0.0}"
      local W2_PORT="${NOETL_WORKER2_PORT:-9081}"
      local W2_CHECK_HOST="$W2_HOST"; [[ "$W2_CHECK_HOST" == "0.0.0.0" ]] && W2_CHECK_HOST="127.0.0.1"
      if port_in_use "$W2_CHECK_HOST" "$W2_PORT"; then
        echo "worker2-api-dev did not start because the port is already in use. Assuming another instance is running. See $LOG_DIR/worker2.log"
        if pid=$(find_pid_by_port "$W2_PORT"); then
          echo "$pid" > "$PID_DIR/worker2.pid"
          echo "worker2-api-dev: captured existing PID $pid listening on port $W2_PORT"
        fi
      else
        # Use dedicated Makefile target that maps NOETL_WORKER2_* to primary envs
        start_service "worker2-api-dev" "make run-worker2-api-dev" "$LOG_DIR/worker2.log" "$PID_DIR/worker2.pid"
      fi
    fi

    echo "Started. Logs in '$LOG_DIR/'. Use: $0 tail"
    ;;
  stop)
    # Also stop any tailers
    kill_tailers || true
    # Attempt graceful deregistration for worker and broker before killing processes
    if [[ -f "/tmp/noetl_worker_pool_name" ]]; then
      WNAME=$(cat /tmp/noetl_worker_pool_name || true)
      if [[ -n "$WNAME" ]]; then
        echo "Calling server to deregister worker pool: $WNAME"
        curl -s -X DELETE "${NOETL_SERVER_URL:-http://localhost:8082}/api/worker/pool/deregister" -H 'Content-Type: application/json' -d "{\"name\": \"$WNAME\"}" || true
        rm -f /tmp/noetl_worker_pool_name || true
      fi
    fi
    # Broker name may be environment-driven; attempt best-effort deregister
    if [[ -n "${NOETL_BROKER_NAME:-}" ]]; then
      echo "Calling server to deregister broker: ${NOETL_BROKER_NAME}"
      curl -s -X DELETE "${NOETL_SERVER_URL:-http://localhost:8082}/api/broker/deregister" -H 'Content-Type: application/json' -d "{\"name\": \"${NOETL_BROKER_NAME}\"}" || true
    fi
    stop_service "worker2-api-dev" "$PID_DIR/worker2.pid"
    stop_service "worker-api-dev" "$PID_DIR/worker.pid"
    stop_service "broker"         "$PID_DIR/broker.pid"
    stop_service "server-api-dev" "$PID_DIR/server.pid"
    echo "Stopped."
    ;;
  status)
    status_service "server-api-dev" "$PID_DIR/server.pid"
    status_service "broker"         "$PID_DIR/broker.pid"
    status_service "worker-api-dev" "$PID_DIR/worker.pid"
    status_service "worker2-api-dev" "$PID_DIR/worker2.pid"
    echo "-- Ports --"
    status_port "server" "${NOETL_HOST:-0.0.0.0}" "${NOETL_PORT:-8082}"
    status_port "worker" "${NOETL_WORKER_HOST:-0.0.0.0}" "${NOETL_WORKER_PORT:-8081}"
    if [[ "${NOETL_WORKER2_ENABLE:-false}" =~ ^(1|true|yes|on)$ ]]; then
      status_port "worker2" "${NOETL_WORKER2_HOST:-0.0.0.0}" "${NOETL_WORKER2_PORT:-9081}"
    fi
    ;;
  tail)
    tail_all
    ;;
  tail-stop)
    kill_tailers
    ;;
  less)
    # Usage: bin/dev_detach.sh less [server|broker|worker|worker2]
    target="${2:-server}"
    # Stop background tailers to avoid competing readers
    kill_tailers || true
    case "$target" in
      server) lf="$LOG_DIR/server.log";;
      broker) lf="$LOG_DIR/broker.log";;
      worker) lf="$LOG_DIR/worker.log";;
      worker2) lf="$LOG_DIR/worker2.log";;
      *) echo "Unknown log '$target'. Use one of: server|broker|worker|worker2"; exit 2;;
    esac
    touch "$lf"
    echo "Opening $lf with less. Tip: it starts in follow mode (+F). Press Ctrl+C to stop following, navigate with arrows/PgUp/PgDn, 'q' to quit."
    # -R: raw control chars for colors; +F: follow
    LESS="-R" exec less +F "$lf"
    ;;
  *)
    echo "Usage: $0 {start|stop|status|tail|tail-stop|less [server|broker|worker|worker2]}"
    exit 1
    ;;
esac
