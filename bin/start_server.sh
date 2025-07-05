#!/bin/bash

# Script to load environment variables and start the NoETL server
# Usage: ./bin/start_server.sh [dev|prod|test]

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BASE_DIR="$DIR/.."

ENV="${1:-dev}"

echo "Starting NoETL server with $ENV environment."

source "$DIR/load_env.sh" "$ENV"

cd "$BASE_DIR"
noetl server