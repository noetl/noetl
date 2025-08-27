#!/bin/bash
# NoETL Multiple Workers Stop Script
# This script helps stop all NoETL workers

echo "Stopping NoETL Multiple Workers..."
echo ""

force_stop_worker() {
    local pid="$1"
    local worker_name="$2"

    if [ -n "$pid" ] && [ "$pid" -gt 0 ]; then
        echo "  Force stopping $worker_name (PID: $pid)..."
        kill -9 "$pid" 2>/dev/null || true
    fi
}

deregister_worker() {
    local worker_name="$1"
    local server_url="${NOETL_SERVER_URL:-http://localhost:8083}"

    echo "  Deregistering $worker_name via API..."

    curl -s -X DELETE "${server_url}/api/worker/pool/deregister" \
         -H "Content-Type: application/json" \
         -d "{\"name\": \"$worker_name\"}" >/dev/null 2>&1

    if [ $? -eq 0 ]; then
        echo "  $worker_name deregistered via API"
    else
        echo "  API deregister failed for $worker_name"
    fi
}

echo "Step 1: Stopping workers with PID files..."
if ls ~/.noetl/noetl_worker_*.pid 1> /dev/null 2>&1; then
    echo "Found workers with PID files:"
    ls -la ~/.noetl/noetl_worker_*.pid | while read line; do
        pid_file=$(echo $line | awk '{print $9}')
        if [ -f "$pid_file" ]; then
            worker_name=$(basename "$pid_file" | sed 's/noetl_worker_//' | sed 's/.pid//')
            pid=$(cat "$pid_file")
            echo "  - $worker_name (PID: $pid)"
        fi
    done
    echo ""

    echo "Stopping workers with PID files..."
    for pid_file in ~/.noetl/noetl_worker_*.pid; do
        if [ -f "$pid_file" ]; then
            worker_name=$(basename "$pid_file" | sed 's/noetl_worker_//' | sed 's/.pid//')
            pid=$(cat "$pid_file")
            echo "  Stopping $worker_name..."

            if ! noetl worker stop --name "$worker_name" --force 2>/dev/null; then
                echo "  Graceful stop failed, force killing PID $pid..."
                force_stop_worker "$pid" "$worker_name"
            fi

            deregister_worker "$worker_name"

            rm -f "$pid_file"
            echo "  $worker_name stopped and cleaned up"
        fi
    done
else
    echo "No workers with PID files found."
fi

echo ""
echo " Step 2: Cleaning up orphaned worker processes..."
worker_processes=$(ps aux | grep "noetl worker start" | grep -v grep | awk '{print $2}')
if [ -n "$worker_processes" ]; then
    echo "Found orphaned worker processes:"
    ps aux | grep "noetl worker start" | grep -v grep | while read line; do
        pid=$(echo $line | awk '{print $2}')
        echo "  - PID: $pid (orphaned)"
    done
    echo ""

    echo "Force killing orphaned processes..."
    for pid in $worker_processes; do
        echo "  Force killing orphaned worker PID $pid..."
        kill -9 "$pid" 2>/dev/null || true
    done
else
    echo "No orphaned worker processes found."
fi

echo ""
echo " Step 3: Ensuring all workers are marked offline in database..."
deregister_worker "worker-cpu-01"
deregister_worker "worker-cpu-02"
deregister_worker "worker-gpu-01"

echo ""
echo " Step 4: Final cleanup..."
pkill -f "noetl worker stop" 2>/dev/null || true

rm -f ~/.noetl/noetl_worker_*.pid

echo ""
echo " Worker stop process completed!"
echo ""
echo " Verification:"
echo "   ls ~/.noetl/noetl_worker_*.pid  # Should show no files"
echo "   ps aux | grep 'noetl worker' | grep -v grep  # Should show no processes"
echo ""
echo " Check database status at: http://localhost:8083/api/worker/pools"