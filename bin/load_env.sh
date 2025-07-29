#!/bin/bash

# Script to load environment variables from separate .env files
# Usage: source bin/load_env_files.sh [dev|prod|test]

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BASE_DIR="$DIR"

ENV="${1:-}"

ENV_COMMON="$BASE_DIR/.env.common"
ENV_FILE="$BASE_DIR/.env${ENV:+.$ENV}"

echo "Loading environment variables${ENV:+ for $ENV environment}."

if [[ -f "$ENV_COMMON" ]]; then
    echo "Loading common variables from $ENV_COMMON"
    set -a
    source "$ENV_COMMON"
    set +a
fi

  # Special case for tradetrend environment
  if [ "$ENV" = "tradetrend" ]; then
    echo "Setting up PostgreSQL port 5432 for tradetrend environment"
    export POSTGRES_PORT=5432
  fi

if [[ -f "$ENV_FILE" ]]; then
    echo "Loading${ENV:+ $ENV} environment variables from $ENV_FILE"
    set -a
    source "$ENV_FILE"
    set +a
else
    echo "Warning: Environment file $ENV_FILE not found"
fi

echo "Environment variables loaded successfully."