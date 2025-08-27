#!/bin/bash
# NoETL Multiple Workers Startup Script
# This script helps start multiple NoETL workers with different configurations

set -e

echo "Starting NoETL Multiple Workers..."
echo ""

start_worker() {
    local env_file="$1"
    local worker_name="$2"
    local worker_pool_name="$3"

    if [ ! -f "$env_file" ]; then
        echo "Error: Environment file $env_file not found!"
        return 1
    fi

    echo "Starting $worker_name using $env_file..."

    (
        set -a
        source "$env_file"
        set +a
        make worker-start
    )

    local log_file="logs/worker_${worker_pool_name}.log"

    echo "$worker_name started successfully!"
    echo "   Logs: $log_file"
    echo ""
}

# Start CPU Worker 01
start_worker ".env.worker-cpu-01" "CPU Worker 01" "worker_cpu_01"

# Start CPU Worker 02
start_worker ".env.worker-cpu-02" "CPU Worker 02" "worker_cpu_02"

# Start GPU Worker 01
start_worker ".env.worker-gpu-01" "GPU Worker 01" "worker_gpu_01"

echo "All workers started successfully."
echo ""
echo "Check running workers:"
echo "   ls ~/.noetl/noetl_worker_*.pid"
echo "   ps aux | grep 'noetl worker' | grep -v grep"
echo ""
echo "Worker-specific logs:"
echo "   logs/worker_worker_cpu_01.log"
echo "   logs/worker_worker_cpu_02.log"
echo "   logs/worker_worker_gpu_01.log"
echo ""
echo "To stop workers:"
echo "   make worker-stop  # Interactive selection"
echo "   noetl worker stop --name worker-cpu-01  # Stop specific worker"
