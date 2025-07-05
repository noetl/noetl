#!/bin/bash

# Script to load environment variables from separate .env files
# Usage: source bin/load_env_files.sh [dev|prod|test]

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BASE_DIR="$DIR/.."

ENV="${1:-dev}"

ENV_COMMON="$BASE_DIR/.env.common"
ENV_FILE="$BASE_DIR/.env.$ENV"
ENV_LOCAL="$BASE_DIR/.env.local"

echo "Loading environment variables for $ENV environment."

if [[ -f "$ENV_COMMON" ]]; then
    echo "Loading common variables from $ENV_COMMON"
    set -a
    source "$ENV_COMMON"
    set +a
fi

if [[ -f "$ENV_FILE" ]]; then
    echo "Loading $ENV environment variables from $ENV_FILE"
    set -a
    source "$ENV_FILE"
    set +a
else
    echo "Warning: Environment file $ENV_FILE not found"
fi

if [[ -f "$ENV_LOCAL" ]]; then
    echo "Loading local overrides from $ENV_LOCAL"
    set -a
    source "$ENV_LOCAL"
    set +a
fi

echo "Environment variables loaded successfully."