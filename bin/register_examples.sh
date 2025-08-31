#!/bin/bash

PORT=${1:-8080}
HOST=${2:-localhost}

echo "Loading playbooks on $HOST port $PORT"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
NOETL_CLI="$REPO_ROOT/.venv/bin/noetl"
if [ ! -x "$NOETL_CLI" ]; then
  NOETL_CLI="noetl"
fi

PLAYBOOKS=(
  "examples/weather/weather_example.yaml"
  "examples/batch/multi_playbook_example.yaml"
  "examples/google_secret_manager/secrets_test.yaml"
  "examples/google_secret_manager/gcs_secrets_example.yaml"
  "examples/weather/weather_loop_example.yaml"
  "examples/postgres/postgres_test.yaml"
  "examples/duckdb/load_dict_test.yaml"
  "examples/duckdb/gs_duckdb_postgres_example.yaml"
  "examples/amadeus/amadeus_api_playbook.yaml"
  "examples/wikipedia/wikipedia_duckdb_postgres_example.yaml"
  "examples/github/github_metrics_example.yaml"
)

for playbooks in "${PLAYBOOKS[@]}"; do
  echo "Loading $playbooks"

  if "$NOETL_CLI" register "$playbooks" --port "$PORT" --host "$HOST"; then
    echo "✓ loaded $playbooks"
  else
    echo "✗ Failed $playbooks"
  fi

  echo "------------------------"
done

echo "Playbooks loaded."
