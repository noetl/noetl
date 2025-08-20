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

start_service() {
  local name="$1" command="$2" logfile="$3" pidfile="$4"
  : > "$logfile"
  echo "Starting $name -> $logfile"
  nohup bash -c "source .env >/dev/null 2>&1 || true; exec $command" >>"$logfile" 2>&1 &
  echo $! > "$pidfile"
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

tail_all() {
  touch "$LOG_DIR/server.log" "$LOG_DIR/broker.log" "$LOG_DIR/worker.log"

  trap 'kill $(jobs -p) 2>/dev/null || true; exit 0' INT TERM

  tail -n +1 -F "$LOG_DIR/server.log" | awk '{ print "[server] " $0 }' &
  p1=$!
  tail -n +1 -F "$LOG_DIR/broker.log" | awk '{ print "[broker] " $0 }' &
  p2=$!
  tail -n +1 -F "$LOG_DIR/worker.log" | awk '{ print "[worker] " $0 }' &
  p3=$!
  echo "Tailing all logs. Ctrl+C to exit."
  wait $p1 $p2 $p3
}

cmd="${1:-}"
case "$cmd" in
  start)
    start_service "server-api-dev" "python -m uvicorn noetl.main:app --host 0.0.0.0 --port 8080 --reload" "$LOG_DIR/server.log" "$PID_DIR/server.pid"
    start_service "broker"         "python -c 'from noetl.broker import main; main()'" "$LOG_DIR/broker.log" "$PID_DIR/broker.pid"
    start_service "worker-api-dev" "python -c 'from noetl.worker import main; main()'" "$LOG_DIR/worker.log" "$PID_DIR/worker.pid"
    echo "Started. Logs in '$LOG_DIR/'. Use: $0 tail"
    ;;
  stop)
    stop_service "worker-api-dev" "$PID_DIR/worker.pid"
    stop_service "broker"         "$PID_DIR/broker.pid"
    stop_service "server-api-dev" "$PID_DIR/server.pid"
    echo "Stopped."
    ;;
  status)
    status_service "server-api-dev" "$PID_DIR/server.pid"
    status_service "broker"         "$PID_DIR/broker.pid"
    status_service "worker-api-dev" "$PID_DIR/worker.pid"
    ;;
  tail)
    tail_all
    ;;
  *)
    echo "Usage: $0 {start|stop|status|tail}"
    exit 1
    ;;
esac
