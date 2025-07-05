#!/bin/bash

# Script to load environment variables and run the NoETL agent
# Usage: ./bin/run_agent.sh [dev|prod|test] -f playbook_file.yaml [other_options]

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BASE_DIR="$DIR/.."

ENV="${1:-dev}"
shift

echo "Running NoETL agent with $ENV environment..."

source "$DIR/load_env.sh" "$ENV"

cd "$BASE_DIR"
noetl agent "$@"