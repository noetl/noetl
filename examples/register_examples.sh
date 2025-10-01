#!/bin/bash

PORT=${1:-8080}
HOST=${2:-localhost}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
EXAMPLES_ROOT="$REPO_ROOT/examples"
NOETL_CLI="$REPO_ROOT/.venv/bin/noetl"
if [ ! -x "$NOETL_CLI" ]; then
  NOETL_CLI="noetl"
fi

echo "Loading example playbooks on $HOST port $PORT"

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
done < <(find "$EXAMPLES_ROOT" -type f \( -name '*.yaml' -o -name '*.yml' \) ! -path '*/test/*' -print0)

if [ "$FOUND" = false ]; then
  echo "No example playbooks found under $EXAMPLES_ROOT" >&2
  exit 1
fi

echo "Example playbooks loaded."
