#!/bin/bash

PORT=${1:-8080}
HOST=${2:-localhost}

echo "Loading playbooks on $HOST port $PORT"

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
  "examples/iac/gcp_vm_control_loop.yaml"
  "examples/credentials/http_bearer_example.yaml"
  "examples/quantum/grover_qiskit_playbook.yaml"
)

for playbooks in "${PLAYBOOKS[@]}"; do
  echo "Loading $playbooks"

  if noetl register "$playbooks" --port "$PORT" --host "$HOST"; then
    echo "✓ loaded $playbooks"
  else
    echo "✗ Failed $playbooks"
  fi

  echo "------------------------"
done

echo "Playbooks loaded."
