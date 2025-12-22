#!/bin/bash

# Script to test loading environment variables from separate .env files
# Usage: ./bin/test_env_files.sh [dev|prod|test]

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

source "$DIR/load_env.sh" "$1"

echo ""
echo "Environment variables loaded:"
echo "----------------------------"
echo "Common variables:"
echo "PRJDIR: $PRJDIR"
echo "PYTHONPATH: $PYTHONPATH"
echo "GOOGLE_APPLICATION_CREDENTIALS: $GOOGLE_APPLICATION_CREDENTIALS"
echo ""
echo "Environment-specific variables:"
echo "GOOGLE_SECRET_POSTGRES_PASSWORD: $GOOGLE_SECRET_POSTGRES_PASSWORD"
echo "GOOGLE_SECRET_API_KEY: $GOOGLE_SECRET_API_KEY"
echo "LASTPASS_USERNAME: $LASTPASS_USERNAME"
echo "LASTPASS_PASSWORD: ${LASTPASS_PASSWORD:0:3}**** masked ****"
echo ""
echo "Current environment: $ENV"