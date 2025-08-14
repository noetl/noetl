#!/usr/bin/env bash
set -euo pipefail

# Helper to test NoETL GCP token endpoint with curl
# Usage examples:
#   ./test-gcp-token.sh --port 8084 --scopes https://www.googleapis.com/auth/cloud-platform \
#       --credentials-path /opt/noetl/.secrets/noetl-service-account.json
#
#   ./test-gcp-token.sh --port 8084 --scopes https://www.googleapis.com/auth/cloud-platform \
#       --service-account-secret projects/1234567890/secrets/noetl-service-account/versions/1
#
#   ./test-gcp-token.sh --port 8084 --credentials-info-file .secrets/noetl-service-account.json
#
#   ./test-gcp-token.sh --host localhost --port 8080 --use-metadata true

HOST="localhost"
PORT="${NOETL_PORT:-8084}"
SCOPES="https://www.googleapis.com/auth/cloud-platform"
CREDENTIALS_PATH=""
USE_METADATA="false"
SA_SECRET=""
CREDENTIALS_INFO_FILE=""
TIMEOUT=30
ENDPOINT=""
STORE_AS=""
STORE_TAGS=""
STORE_DESCRIPTION=""
STORE_TYPE=""

print_usage(){
  cat <<EOF
NoETL GCP Token tester

Options:
  --host HOST                     Default: ${HOST}
  --port PORT                     Default: ${PORT}
  --endpoint URL                  Full URL override (e.g. http://localhost:8084/api/gcp/token)
  --scopes SCOPES                 Space/comma separated list or single scope (default: ${SCOPES})
  --credentials-path PATH         Path to service account JSON file inside the container/host
  --service-account-secret PATH   Google Secret Manager resource path (projects/.../secrets/.../versions/..)
  --credentials-info-file PATH    Path to JSON file containing service account key to embed into request body
  --use-metadata true|false       Try ADC/metadata first (default: ${USE_METADATA})
  --timeout SECONDS               Curl timeout (default: ${TIMEOUT})
  --store-as NAME                 Persist token under this credential name (type httpBearerAuth by default)
  --store-type TYPE               Optional credential type when storing (default: httpBearerAuth)
  --store-description TEXT        Optional description for the stored token
  --store-tags CSV                Optional comma-separated tags for the stored token
  --help                          Show help

Examples:
  $0 --port 8084 --credentials-path /opt/noetl/.secrets/noetl-service-account.json
  $0 --port 8084 --service-account-secret projects/123/secrets/noetl-service-account/versions/1
  $0 --port 8084 --credentials-info-file .secrets/noetl-service-account.json
  $0 --port 8080 --use-metadata true
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2;;
    --port) PORT="$2"; shift 2;;
    --endpoint) ENDPOINT="$2"; shift 2;;
    --scopes) SCOPES="$2"; shift 2;;
    --credentials-path) CREDENTIALS_PATH="$2"; shift 2;;
    --service-account-secret) SA_SECRET="$2"; shift 2;;
    --credentials-info-file) CREDENTIALS_INFO_FILE="$2"; shift 2;;
    --use-metadata) USE_METADATA="$2"; shift 2;;
    --timeout) TIMEOUT="$2"; shift 2;;
    --store-as) STORE_AS="$2"; shift 2;;
    --store-type) STORE_TYPE="$2"; shift 2;;
    --store-description) STORE_DESCRIPTION="$2"; shift 2;;
    --store-tags) STORE_TAGS="$2"; shift 2;;
    --help|-h) print_usage; exit 0;;
    *) echo "Unknown option: $1"; print_usage; exit 1;;
  esac
done

if [[ -z "${ENDPOINT}" ]]; then
  ENDPOINT="http://${HOST}:${PORT}/api/gcp/token"
fi


IFS=',' read -r -a SCOPES_ARR <<< "${SCOPES// /,}"
SCOPES_JSON="[\"${SCOPES_ARR[0]}\"]"
if [[ ${#SCOPES_ARR[@]} -gt 1 ]]; then
  SCOPES_JSON="[\"$(printf "%s\",\"" "${SCOPES_ARR[@]}" | sed 's/,"$//')\"]"
fi

PAYLOAD="{\n  \"scopes\": ${SCOPES_JSON},\n  \"use_metadata\": ${USE_METADATA}"

if [[ -n "${CREDENTIALS_PATH}" ]]; then
  PAYLOAD+="\n, \"credentials_path\": \"${CREDENTIALS_PATH}\""
fi

if [[ -n "${SA_SECRET}" ]]; then
  PAYLOAD+="\n, \"service_account_secret\": \"${SA_SECRET}\""
fi

if [[ -n "${CREDENTIALS_INFO_FILE}" ]]; then
  if [[ ! -f "${CREDENTIALS_INFO_FILE}" ]]; then
    echo "credentials-info-file not found: ${CREDENTIALS_INFO_FILE}" >&2
    exit 1
  fi
  ESCAPED=$(python3 - <<PY
import json,sys
with open(${CREDENTIALS_INFO_FILE!r}, 'rb') as f:
    data = f.read().decode('utf-8')
try:
    obj = json.loads(data)
    print(json.dumps(obj))
except Exception:
    print(json.dumps(data))
PY
)
  PAYLOAD+="\n, \"credentials_info\": ${ESCAPED}"
fi

PAYLOAD+="\n}"

echo "Calling: ${ENDPOINT}" >&2
echo "Payload:" >&2
echo "${PAYLOAD}" >&2

set +e
RESP=$(curl -sS --fail --connect-timeout ${TIMEOUT} --max-time ${TIMEOUT} \
  -H 'Content-Type: application/json' \
  -X POST "${ENDPOINT}" \
  -d "${PAYLOAD}")
STATUS=$?
set -e

if [[ $STATUS -ne 0 ]]; then
  echo "curl failed with status ${STATUS}" >&2
  exit ${STATUS}
fi

echo "Response:" >&2
printf "%s\n" "${RESP}"

if command -v jq >/dev/null 2>&1; then
  TOKEN=$(echo "${RESP}" | jq -r '.access_token // empty') || true
  if [[ -n "${TOKEN}" ]]; then
    echo
    echo "access_token:" 
    echo "${TOKEN}"
  fi
fi
