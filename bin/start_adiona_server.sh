#!/bin/bash

# Start NoETL server with adiona.env configuration
# Usage: ./bin/start_adiona_server.sh [port]

PORT=${1:-8081}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "Starting NoETL server with adiona.env configuration..."
echo "Port: $PORT"
echo "Project root: $PROJECT_ROOT"

# Load environment variables from adiona.env
if [ -f "$PROJECT_ROOT/adiona.env" ]; then
    echo "Loading environment from adiona.env..."
    export $(cat "$PROJECT_ROOT/adiona.env" | grep -v '^#' | xargs)
    echo "Environment loaded:"
    echo "  - NOETL_ENABLE_UI: $NOETL_ENABLE_UI"
    echo "  - POSTGRES_DB: $POSTGRES_DB"
    echo "  - POSTGRES_USER: $POSTGRES_USER"
    echo "  - POSTGRES_HOST: $POSTGRES_HOST"
    echo "  - POSTGRES_PORT: $POSTGRES_PORT"
else
    echo "Error: adiona.env file not found in $PROJECT_ROOT"
    exit 1
fi

# Change to project directory
cd "$PROJECT_ROOT"

# Start the server
echo "Starting NoETL server..."
python -m noetl.main server --host 0.0.0.0 --port "$PORT"
