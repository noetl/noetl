#!/bin/bash
# Create GCS service account for NoETL script execution

set -e

GCP_PROJECT="${GCP_PROJECT:-noetl-demo-19700101}"
SA_NAME="noetl-script-executor"
SA_EMAIL="${SA_NAME}@${GCP_PROJECT}.iam.gserviceaccount.com"
KEY_FILE="tests/fixtures/credentials/gcs_service_account.json"

echo "🔧 Setting up GCS service account for NoETL"
echo "Project: $GCP_PROJECT"
echo "Service Account: $SA_EMAIL"
echo ""

# Set project
gcloud config set project "$GCP_PROJECT"

# Check if service account exists
if gcloud iam service-accounts describe "$SA_EMAIL" &>/dev/null; then
    echo "✓ Service account already exists: $SA_EMAIL"
else
    echo "Creating service account..."
    gcloud iam service-accounts create "$SA_NAME" \
        --display-name="NoETL Script Executor" \
        --description="Service account for NoETL K8s job script execution with GCS access"
    echo "✓ Created service account: $SA_EMAIL"
fi

# Grant Storage Object Creator role (allows creating/writing objects)
echo "Granting Storage Object Admin role..."
gcloud projects add-iam-policy-binding "$GCP_PROJECT" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/storage.objectAdmin" \
    --condition=None

echo "✓ Granted roles/storage.objectAdmin"

# Create and download key
if [ -f "$KEY_FILE" ]; then
    echo "⚠️  Key file already exists: $KEY_FILE"
    read -p "Overwrite? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Skipping key creation. Using existing file."
        KEY_FILE_EXISTS=true
    fi
fi

if [ -z "$KEY_FILE_EXISTS" ]; then
    echo "Creating service account key..."
    mkdir -p "$(dirname "$KEY_FILE")"
    gcloud iam service-accounts keys create "$KEY_FILE" \
        --iam-account="$SA_EMAIL"
    echo "✓ Downloaded key to: $KEY_FILE"
fi

# Create NoETL credential JSON
CRED_FILE="tests/fixtures/credentials/gcs_service_account_noetl.json"
echo "Creating NoETL credential file..."

cat > "$CRED_FILE" << EOF
{
  "name": "gcs_service_account",
  "type": "gcs_service_account",
  "description": "GCS service account for script execution (${SA_EMAIL})",
  "tags": ["gcs", "service-account", "script-executor"],
  "data": {
    "service_account_json": $(cat "$KEY_FILE")
  }
}
EOF

echo "✓ Created NoETL credential: $CRED_FILE"
echo ""
echo "📋 Next steps:"
echo "1. Register credential with NoETL:"
echo "   curl -X POST http://localhost:8082/api/credentials \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     --data-binary @$CRED_FILE"
echo ""
echo "2. Update playbook to use 'gcs_service_account' credential"
echo ""
echo "3. Execute playbook:"
echo "   .venv/bin/noetl execute playbook 'tests/script_execution/k8s_job_python_gcs' \\"
echo "     --host localhost --port 8082"
