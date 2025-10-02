#!/bin/bash
# Port-forward script for unified observability

NAMESPACE="noetl-platform"

# Function to start port-forward in background
start_port_forward() {
    local service=$1
    local local_port=$2
    local remote_port=$3
    local name=$4
    
    # Kill existing process if running
    pkill -f "kubectl.*port-forward.*${service}" || true
    sleep 1
    
    echo "Starting port-forward for ${name}: localhost:${local_port}"
    kubectl port-forward -n "${NAMESPACE}" "service/${service}" "${local_port}:${remote_port}" > "/tmp/pf-${name}.log" 2>&1 &
    echo $! > "/tmp/pf-${name}.pid"
}

case "$1" in
    start)
        echo "Starting port-forwards for unified observability..."
        start_port_forward "vmstack-grafana" 3000 80 "grafana"
        start_port_forward "vlogs-victoria-logs-single-server" 9428 9428 "vlogs"
        start_port_forward "vmsingle-vmstack-victoria-metrics-k8s-stack" 8428 8428 "vmsingle"
        echo "Port-forwards started. Services available at:"
        echo "  - Grafana:            http://localhost:3000"
        echo "  - VictoriaLogs UI:    http://localhost:9428"
        echo "  - VictoriaMetrics UI: http://localhost:8428/vmui/"
        ;;
    stop)
        echo "Stopping all port-forwards..."
        for pid_file in /tmp/pf-*.pid; do
            if [ -f "$pid_file" ]; then
                pid=$(cat "$pid_file")
                kill "$pid" 2>/dev/null || true
                rm "$pid_file"
            fi
        done
        pkill -f "kubectl.*port-forward.*vmstack-grafana" || true
        pkill -f "kubectl.*port-forward.*vlogs-victoria-logs-single-server" || true
        pkill -f "kubectl.*port-forward.*vmsingle-vmstack-victoria-metrics-k8s-stack" || true
        echo "Port-forwards stopped."
        ;;
    status)
        echo "Port-forward status:"
        for pid_file in /tmp/pf-*.pid; do
            if [ -f "$pid_file" ]; then
                pid=$(cat "$pid_file")
                if kill -0 "$pid" 2>/dev/null; then
                    name=$(basename "$pid_file" .pid | sed 's/pf-//')
                    echo "  ${name}: RUNNING (PID: $pid)"
                else
                    echo "  ${name}: STOPPED"
                fi
            fi
        done
        ;;
    *)
        echo "Usage: $0 {start|stop|status}"
        exit 1
        ;;
esac
