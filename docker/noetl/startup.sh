#!/bin/bash
set -e

echo "=== ENVIRONMENT VARIABLES AT STARTUP ==="
env | sort
echo "=== END ENVIRONMENT VARIABLES ==="

# Get run mode from environment variable (default to server)
RUN_MODE=${NOETL_RUN_MODE:-server}
echo "Starting NoETL in $RUN_MODE mode"

# Get host and port from environment variables
HOST=${NOETL_HOST:-0.0.0.0}
PORT=${NOETL_PORT:-8080}

# Get debug flag from environment variable
DEBUG_FLAG=""
if [ "${NOETL_DEBUG:-false}" = "true" ]; then
  DEBUG_FLAG="--debug"
fi

# Execute the appropriate command based on run mode
case $RUN_MODE in
  server)
    # Get workers from environment variable (default to 1)
    WORKERS=${NOETL_WORKERS:-1}
    
    # Get reload flag from environment variable
    RELOAD_FLAG=""
    if [ "${NOETL_RELOAD:-false}" = "true" ]; then
      RELOAD_FLAG="--reload"
    fi
    
    # Get no-ui flag from environment variable
    NOUI_FLAG=""
    if [ "${NOETL_NO_UI:-false}" = "true" ]; then
      NOUI_FLAG="--no-ui"
    fi
    
    echo "Starting NoETL server on $HOST:$PORT with $WORKERS workers"
    exec noetl server start --host "$HOST" --port "$PORT" --workers "$WORKERS" $RELOAD_FLAG $NOUI_FLAG $DEBUG_FLAG
    ;;
  server-stop)
    # Get force flag from environment variable
    FORCE_FLAG=""
    if [ "${NOETL_FORCE_STOP:-false}" = "true" ]; then
      FORCE_FLAG="--force"
    fi
    
    echo "Stopping NoETL server"
    exec noetl server stop $FORCE_FLAG
    ;;
  worker)
    # Get playbook path from environment variable
    PLAYBOOK_PATH=${NOETL_PLAYBOOK_PATH:-}
    if [ -z "$PLAYBOOK_PATH" ]; then
      echo "Error: NOETL_PLAYBOOK_PATH environment variable is required for worker mode"
      exit 1
    fi
    
    # Get optional version from environment variable
    VERSION_FLAG=""
    if [ -n "${NOETL_PLAYBOOK_VERSION:-}" ]; then
      VERSION_FLAG="--version ${NOETL_PLAYBOOK_VERSION}"
    fi
    
    # Get mock mode flag from environment variable
    MOCK_FLAG=""
    if [ "${NOETL_MOCK_MODE:-false}" = "true" ]; then
      MOCK_FLAG="--mock"
    fi
    
    echo "Starting NoETL worker for playbook: $PLAYBOOK_PATH"
    exec noetl worker "$PLAYBOOK_PATH" $VERSION_FLAG $MOCK_FLAG $DEBUG_FLAG
    ;;
  cli)
    # For CLI mode, we just keep the container running
    # Users can exec into it and run noetl commands
    echo "NoETL container started in CLI mode"
    echo "Use 'docker exec -it <container_name> noetl <command>' to run commands"
    # Keep the container running
    exec tail -f /dev/null
    ;;
  *)
    echo "Error: Unknown run mode: $RUN_MODE"
    echo "Supported modes: server, worker, cli"
    exit 1
    ;;
esac