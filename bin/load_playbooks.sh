#!/bin/bash

PORT=${1:-8080}
HOST=${2:-localhost}

echo "Loading playbooks on $HOST port $PORT"

PLAYBOOKS=(
  "playbook/weather.yaml"
  "playbook/multi_playbook_example.yaml"
  "playbook/secrets_test.yaml"
  "playbook/weather_example.yaml"
  "playbook/postgres_test.yaml"
  "playbook/load_dict_test.yaml"
  "playbook/gs_duckdb_postgres_example.yaml"
  "playbook/gcs_secrets_example.yaml"
)

for playbook in "${PLAYBOOKS[@]}"; do
  echo "Loading $playbook"

  if noetl playbook --register "$playbook" --port "$PORT" --host "$HOST"; then
    echo "✓ loaded $playbook"
  else
    echo "✗ Failed $playbook"
  fi

  echo "------------------------"
done

echo "Playbooks loaded."
