#!/bin/bash

# Navigate to the project directory
cd /Users/ndrpt/noetl/noetl

# Activate virtual environment
source .venv/bin/activate

# Load environment variables
source bin/load_env.sh

# Explicitly export critical environment variables
export NOETL_SCHEMA=${NOETL_SCHEMA:-noetl}
export NOETL_USER=${NOETL_USER:-noetl}
export NOETL_PASSWORD=${NOETL_PASSWORD:-noetl}

# Verify environment variables are set
echo "Environment variables:"
echo "NOETL_SCHEMA: $NOETL_SCHEMA"
echo "NOETL_USER: $NOETL_USER"
echo "POSTGRES_HOST: $POSTGRES_HOST"
echo "POSTGRES_PORT: $POSTGRES_PORT"

# Start the server
python -m noetl.main server start --host localhost --port 8080 --debug
