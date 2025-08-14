#!/usr/bin/env bash
set -euo pipefail

# Simple helper to register a secret/credential with NoETL
# Usage examples:
#   ./bin/register-secret.sh --name my-bearer --type httpBearerAuth --data '{"token":"XYZ"}'
#   ./bin/register-secret.sh --file examples/credentials/secret_bearer.yaml
#   NOETL_HOST=127.0.0.1 NOETL_PORT=8084 ./bin/register-secret.sh --name my-bearer --type httpBearerAuth --data-file token.json
#
# Requires NOETL_ENCRYPTION_KEY set on the server side.

HOST="${NOETL_HOST:-localhost}"
PORT="${NOETL_PORT:-8080}"
MODE="cli"  # cli | manifest
NAME=""
TYPE=""
DATA_JSON=""
DATA_FILE=""
MANIFEST_FILE=""
DESCRIPTION=""
TAGS=""
META=""
META_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name|-n) NAME="$2"; shift 2;;
    --type|-t) TYPE="$2"; shift 2;;
    --data) DATA_JSON="$2"; shift 2;;
    --data-file) DATA_FILE="$2"; shift 2;;
    --file) MANIFEST_FILE="$2"; MODE="manifest"; shift 2;;
    --description|-d) DESCRIPTION="$2"; shift 2;;
    --tags) TAGS="$2"; shift 2;;
    --meta) META="$2"; shift 2;;
    --meta-file) META_FILE="$2"; shift 2;;
    --host) HOST="$2"; shift 2;;
    --port|-p) PORT="$2"; shift 2;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done

if [[ "$MODE" == "manifest" ]]; then
  if [[ -z "$MANIFEST_FILE" ]]; then
    echo "--file <manifest.yaml> is required in manifest mode" >&2
    exit 1
  fi
  if ! command -v noetl >/dev/null 2>&1; then
    echo "noetl CLI not found in PATH" >&2
    exit 1
  fi
  echo "Registering secret via manifest: $MANIFEST_FILE"
  noetl catalog register secret "$MANIFEST_FILE" --host "$HOST" --port "$PORT"
  exit $?
fi

# CLI mode via direct API
if [[ -z "$NAME" || -z "$TYPE" ]]; then
  echo "--name and --type are required (or use --file manifest mode)." >&2
  exit 1
fi

if [[ -n "$DATA_FILE" ]]; then
  DATA_JSON=$(cat "$DATA_FILE")
fi
if [[ -z "$DATA_JSON" ]]; then
  echo "Either --data or --data-file must be provided." >&2
  exit 1
fi

BODY=$(jq -n \
  --arg name "$NAME" \
  --arg type "$TYPE" \
  --argjson data "$DATA_JSON" \
  --arg description "$DESCRIPTION" \
  --arg tags "$TAGS" \
  --arg meta "$META" \
  '{name: $name, type: $type, data: $data} | (.description = ($description | select(length>0))) | (.tags = ( ($tags|length>0) and ($tags|split(",")) or null)) | (.meta = ( ($meta|length>0) and (try ( $meta|fromjson ) catch null) ))' )

echo "POST http://$HOST:$PORT/api/credentials"
curl -sS -H 'Content-Type: application/json' -X POST \
  -d "$BODY" \
  "http://$HOST:$PORT/api/credentials" | jq .

cat <<'EOF'

Next steps:
1) Confirm your credential exists:
   curl -sS http://$HOST:$PORT/api/credentials | jq .

2) Try the HTTP example using bearer auth (replace the name if different):
   noetl execute examples/credentials/http_bearer_example.yaml --host $HOST --port $PORT

Note: Ensure the server was started with NOETL_ENCRYPTION_KEY set.
EOF
