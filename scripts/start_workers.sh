#!/bin/bash
# NoETL Multiple Workers Startup Script
# This script helps start multiple NoETL workers with different configurations
#
# Features:
# - Prevents duplicate workers (checks PID files and running processes)
# - Cleans up orphaned processes automatically
# - Supports force restart with --force flag
#
# Usage:
#   ./start_multiple_workers.sh          # Start workers (skip if already running)
#   ./start_multiple_workers.sh --force  # Force restart all workers

set -e

FORCE_RESTART=false
if [ "$1" = "--force" ]; then
    FORCE_RESTART=true
    echo " Force restart mode enabled - will stop existing workers first"
    echo ""
fi

echo " Starting NoETL Multiple Workers..."
echo ""

cleanup_orphaned_processes() {
    echo " Checking for orphaned worker processes..."
    local orphaned_count=0
    local worker_processes=$(ps aux | grep "noetl worker start" | grep -v grep | awk '{print $2}')

    for pid in $worker_processes; do
        local has_pid_file=false
        for pid_file in ~/.noetl/noetl_worker_*.pid; do
            if [ -f "$pid_file" ] && [ "$(cat "$pid_file")" = "$pid" ]; then
                has_pid_file=true
                break
            fi
        done

        if [ "$has_pid_file" = false ]; then
            echo "   Found orphaned worker process (PID: $pid) - terminating..."
            kill -9 "$pid" 2>/dev/null || true
            orphaned_count=$((orphaned_count + 1))
        fi
    done

    if [ "$orphaned_count" -gt 0 ]; then
        echo " Cleaned up $orphaned_count orphaned processes"
    else
        echo " No orphaned processes found"
    fi
    echo ""
}

cleanup_orphaned_processes

start_worker() {
    local env_file="$1"
    local worker_name="$2"
    local worker_pool_name="$3"

    if [ ! -f "$env_file" ]; then
        echo " Error: Environment file $env_file not found!"
        return 1
    fi

    local pid_file="$HOME/.noetl/noetl_worker_${worker_pool_name}.pid"
    local worker_already_running=false

    if [ -f "$pid_file" ]; then
        local existing_pid=$(cat "$pid_file")
        if [ -n "$existing_pid" ] && kill -0 "$existing_pid" 2>/dev/null; then
            echo " $worker_name is already running (PID: $existing_pid)"
            worker_already_running=true
        else
            echo "  Cleaning up stale PID file for $worker_name"
            rm -f "$pid_file"
        fi
    fi

    if [ "$worker_already_running" = true ]; then
        if [ "$FORCE_RESTART" = true ]; then
            echo " Force restarting $worker_name (stopping PID: $existing_pid)..."
            kill -TERM "$existing_pid" 2>/dev/null || true
            sleep 2
            rm -f "$pid_file"
            echo ""
        else
            echo "     Skipping $worker_name (already running)"
            echo ""
            return 0
        fi
    fi

    echo " Starting $worker_name using $env_file..."

    (
        set -a
        source "$env_file"
        set +a
        make worker-start
    )

    local log_file="logs/worker_${worker_pool_name}.log"

    echo " $worker_name started successfully."
    echo ""
}

start_worker ".env.worker-cpu-01" "CPU Worker 01" "worker_cpu_01"

start_worker ".env.worker-cpu-02" "CPU Worker 02" "worker_cpu_02"

start_worker ".env.worker-gpu-01" "GPU Worker 01" "worker_gpu_01"

echo " Worker startup process completed."
echo ""
echo " Check running workers:"
echo "   ls ~/.noetl/noetl_worker_*.pid"
echo "   ps aux | grep 'noetl worker' | grep -v grep"
echo ""
echo " Worker-specific logs:"
echo "   logs/worker_worker_cpu_01.log"
echo "   logs/worker_worker_cpu_02.log"
echo "   logs/worker_worker_gpu_01.log"
echo ""
echo " To stop workers:"
echo "   ./bin/stop_multiple_workers.sh  # Stop all workers"
echo "   make worker-stop  # Interactive selection"
echo "   noetl worker stop --name worker-cpu-01  # Stop specific worker"
echo ""
echo " To force restart workers:"
echo "   ./bin/start_multiple_workers.sh --force"
