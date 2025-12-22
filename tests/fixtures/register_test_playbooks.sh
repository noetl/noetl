#!/bin/bash

# Usage:
#   ./tests/fixtures/register_test_playbooks.sh [host] [port]
#   ./tests/fixtures/register_test_playbooks.sh [port] [host]

ARG1=${1:-localhost}
ARG2=${2:-8082}

if [[ "$ARG1" =~ ^[0-9]+$ ]]; then
  PORT="$ARG1"
  HOST="$ARG2"
else
  HOST="$ARG1"
  PORT="$ARG2"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
FIXTURE_ROOT="$REPO_ROOT/tests/fixtures/playbooks"
NOETL_CLI="$REPO_ROOT/.venv/bin/noetl"
if [ ! -x "$NOETL_CLI" ]; then
  NOETL_CLI="noetl"
fi

echo "Loading test fixture playbooks from $FIXTURE_ROOT on $HOST port $PORT"

if [ ! -d "$FIXTURE_ROOT" ]; then
  echo "Fixture directory not found: $FIXTURE_ROOT" >&2
  exit 1
fi

cd "$REPO_ROOT" || exit 1

FOUND=false
while IFS= read -r -d '' playbook; do
  FOUND=true
  rel_path="${playbook#$REPO_ROOT/}"
  echo "Loading $rel_path"

  if "$NOETL_CLI" register "$rel_path" --port "$PORT" --host "$HOST"; then
    echo "✓ loaded $rel_path"
  else
    echo "✗ Failed $rel_path"
  fi

  echo "------------------------"
done < <(find "$FIXTURE_ROOT" -type f \( -name '*.yaml' -o -name '*.yml' \) -print0)

if [ "$FOUND" = false ]; then
  echo "No test fixture playbooks found under $FIXTURE_ROOT" >&2
  exit 1
fi

echo "Test fixture playbooks loaded."
