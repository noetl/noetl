#!/bin/bash

set -e

# Usage: ./setup_noetl_demo.sh <GCP_PROJECT_ID> <SERVICE_ACCOUNT_NAME> <BUCKET_NAME>
# Example: ./setup_noetl_demo.sh noetl-demo-19700101 noetl-demo noetl-demo-bucket

if ! command -v gcloud &> /dev/null; then
    echo "gcloud not found, installing Google Cloud CLI..."

    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Debian/Ubuntu
        if command -v apt-get &> /dev/null; then
            echo "Installing Google Cloud CLI for Debian/Ubuntu..."
            sudo apt-get update && sudo apt-get install -y curl
            curl -O https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-sdk-456.0.0-linux-x86_64.tar.gz
            tar -xf google-cloud-sdk-456.0.0-linux-x86_64.tar.gz
            ./google-cloud-sdk/install.sh
            source ./google-cloud-sdk/path.bash.inc
        # Red Hat/CentOS/Amazon Linux
        elif command -v yum &> /dev/null; then
            echo "Installing Google Cloud CLI for Red Hat/CentOS..."
            sudo yum install -y curl
            curl -O https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-sdk-456.0.0-linux-x86_64.tar.gz
            tar -xf google-cloud-sdk-456.0.0-linux-x86_64.tar.gz
            ./google-cloud-sdk/install.sh
            source ./google-cloud-sdk/path.bash.inc
        else
            echo "Unsupported Linux distribution. Please install Google Cloud CLI manually."
            exit 1
        fi
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        if command -v brew &> /dev/null; then
            echo "Installing Google Cloud CLI using Homebrew..."
            brew install --cask google-cloud-sdk
            source "$(brew --prefix)/Caskroom/google-cloud-sdk/latest/google-cloud-sdk/path.bash.inc" || true
        else
            echo "Installing Google Cloud CLI using official install script..."
            curl -O https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-sdk-456.0.0-darwin-x86_64.tar.gz
            tar -xf google-cloud-sdk-456.0.0-darwin-x86_64.tar.gz
            ./google-cloud-sdk/install.sh
            source ./google-cloud-sdk/path.bash.inc
        fi
    else
        echo "Install Google Cloud CLI manually: https://cloud.google.com/sdk/docs/install"
        exit 1
    fi

    echo "gcloud installed. Please restart your shell or run:"
    echo "  source \$HOME/google-cloud-sdk/path.bash.inc"
    echo "Run this script again."
    exit 0
fi

GCP_PROJECT_ID="$1"
SERVICE_ACCOUNT_NAME="$2"
BUCKET_NAME="$3"
USER_EMAIL=$(gcloud config get-value account)
SECRET_DIR=".secrets"
KEY_FILE="${SECRET_DIR}/${SERVICE_ACCOUNT_NAME}.json"

if [ -z "$GCP_PROJECT_ID" ] || [ -z "$SERVICE_ACCOUNT_NAME" ] || [ -z "$BUCKET_NAME" ]; then
  echo "Usage: $0 <GCP_PROJECT_ID> <SERVICE_ACCOUNT_NAME> <BUCKET_NAME>"
  exit 1
fi

#echo "Creating Google Cloud Project: $GCP_PROJECT_ID"
#gcloud projects create $GCP_PROJECT_ID --name=$GCP_PROJECT_ID
#
#echo "Setting up Google Cloud Project: $GCP_PROJECT_ID"
#gcloud config set project "$GCP_PROJECT_ID"

#echo "Creating service account: $SERVICE_ACCOUNT_NAME"
#gcloud iam service-accounts create "$SERVICE_ACCOUNT_NAME" \
#  --project="$GCP_PROJECT_ID" \
#  --display-name="$SERVICE_ACCOUNT_NAME"

SA_EMAIL="${SERVICE_ACCOUNT_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

#echo "Granting Storage Admin role to service account"
#gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
#  --member="serviceAccount:${SA_EMAIL}" \
#  --role="roles/storage.admin"
#
#echo "Granting user permission to impersonate the service account"
#gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
#  --member="user:${USER_EMAIL}" \
#  --role="roles/iam.serviceAccountTokenCreator"

#echo "Creating bucket: gs://${BUCKET_NAME}"
#gsutil mb -p "$GCP_PROJECT_ID" -c STANDARD -l US "gs://${BUCKET_NAME}"

echo "Enabling S3 interoperability and creating HMAC keys"
HMAC_OUTPUT=$(gcloud alpha storage hmac-keys create "$SA_EMAIL" --project="$GCP_PROJECT_ID" --format=json)
ACCESS_KEY=$(echo "$HMAC_OUTPUT" | grep -o '"accessId": *"[^"]*' | grep -o '[^"]*$')
SECRET_KEY=$(echo "$HMAC_OUTPUT" | grep -o '"secret": *"[^"]*' | grep -o '[^"]*$')
echo "HMAC Access Key: $ACCESS_KEY"
echo "HMAC Secret Key: $SECRET_KEY"

echo "Creating service account key"
mkdir -p "$SECRET_DIR"
gcloud iam service-accounts keys create "$KEY_FILE" --iam-account="$SA_EMAIL"

echo "Setup complete."
echo "Service account key saved to: $KEY_FILE"
echo "HMAC Access Key: $ACCESS_KEY"
echo "HMAC Secret Key: $SECRET_KEY"

cat <<EOF

Next steps:
- Use $KEY_FILE as your GOOGLE_APPLICATION_CREDENTIALS for authentication.
- Use the HMAC Access Key and Secret Key for S3 interoperability (e.g., DuckDB, Polars, etc.).
- Bucket: gs://${BUCKET_NAME}
EOF
