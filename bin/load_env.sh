#!/bin/bash

# Usage: source bin/load_env.sh [dev|prod|test]

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BASE_DIR="$( cd "$DIR/.." && pwd )"

ENV="${1:-}"

ENV_COMMON="$BASE_DIR/.env.common"
ENV_FILE="$BASE_DIR/.env${ENV:+.$ENV}"

if [[ ! -f "$ENV_FILE" ]]; then
    ENV_FILE="$BASE_DIR/.env"
fi

echo "Loading environment variables${ENV:+ for $ENV environment}."

load_env() {
    local env_file="$1"
    if [[ -f "$env_file" ]]; then
        echo "Loading from $env_file"
        set -a
        grep -v '^#' "$env_file" | grep -v '^$' > "${env_file}.tmp"
        source "${env_file}.tmp"
        rm "${env_file}.tmp"
        set +a
    else
        echo "Warning: Environment file $env_file not found"
    fi
}

[[ -f "$ENV_COMMON" ]] && load_env "$ENV_COMMON"

load_env "$ENV_FILE"

echo "Environment variables loaded."