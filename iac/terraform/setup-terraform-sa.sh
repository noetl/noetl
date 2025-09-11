#!/bin/bash

# Setup Terraform Service Account for NoETL Deployment
# This script creates a service account with the necessary permissions to deploy NoETL infrastructure

set -e

PROJECT_ID=${PROJECT_ID:-$(gcloud config get-value project)}
SA_NAME="terraform-noetl"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
KEY_FILE="terraform-sa-key.json"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to cleanup on error
cleanup() {
    if [ $? -ne 0 ]; then
        echo -e "${RED}Script failed. Check the error messages above.${NC}"
        echo -e "${YELLOW}If the service account was partially created, you may need to:${NC}"
        echo -e "${YELLOW}1. Delete the service account: gcloud iam service-accounts delete ${SA_EMAIL}${NC}"
        echo -e "${YELLOW}2. Re-run this script${NC}"
    fi
}
trap cleanup EXIT

echo -e "${BLUE}Setting up Terraform Service Account for NoETL${NC}"
echo -e "${BLUE}Project ID: ${PROJECT_ID}${NC}"
echo -e "${BLUE}Service Account: ${SA_EMAIL}${NC}"

if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
    echo -e "${RED}Error: No active gcloud authentication found${NC}"
    echo -e "${YELLOW}Please run: gcloud auth login${NC}"
    exit 1
fi

if [ -z "$PROJECT_ID" ]; then
    echo -e "${RED}Error: No project ID found${NC}"
    echo -e "${YELLOW}Please run: gcloud config set project YOUR_PROJECT_ID${NC}"
    exit 1
fi

echo -e "${YELLOW}This will create resources in project: ${PROJECT_ID}${NC}"
read -p "Continue? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Aborted${NC}"
    exit 0
fi

echo -e "${BLUE}Enabling required APIs...${NC}"

# Enable required APIs
APIs=(
    "cloudbuild.googleapis.com"
    "run.googleapis.com"
    "sql-component.googleapis.com"
    "sqladmin.googleapis.com"
    "secretmanager.googleapis.com"
    "iam.googleapis.com"
    "cloudresourcemanager.googleapis.com"
    "compute.googleapis.com"
    "container.googleapis.com"
    "artifactregistry.googleapis.com"
    "cloudbilling.googleapis.com"
    "logging.googleapis.com"
    "monitoring.googleapis.com"
)

for api in "${APIs[@]}"; do
    echo -e "  Enabling ${api}..."
    gcloud services enable "${api}" --project="${PROJECT_ID}"
done

echo -e "${GREEN}APIs enabled${NC}"

echo -e "${BLUE}Creating service account...${NC}"

if gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo -e "${YELLOW}Service account ${SA_EMAIL} already exists${NC}"
else
    gcloud iam service-accounts create "${SA_NAME}" \
        --display-name="Terraform Service Account for NoETL" \
        --description="Service account for deploying NoETL infrastructure via Terraform" \
        --project="${PROJECT_ID}"
    echo -e "${GREEN}Service account created${NC}"
    
    # Wait for service account to propagate
    echo -e "${BLUE}Waiting for service account to propagate...${NC}"
    sleep 10
    
    # Verify service account exists before proceeding
    retries=0
    max_retries=10
    while ! gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1; do
        retries=$((retries + 1))
        if [ $retries -ge $max_retries ]; then
            echo -e "${RED}Error: Service account creation failed or took too long to propagate${NC}"
            exit 1
        fi
        echo -e "${YELLOW}Service account not yet available, waiting... (attempt $retries/$max_retries)${NC}"
        sleep 5
    done
    echo -e "${GREEN}Service account confirmed available${NC}"
fi

# Grant IAM roles
echo -e "${BLUE}Granting IAM roles...${NC}"

ROLES=(
    "roles/owner"
    "roles/cloudsql.admin"
    "roles/run.admin"
    "roles/iam.serviceAccountAdmin" 
    "roles/iam.serviceAccountUser"
    "roles/iam.serviceAccountTokenCreator"
    "roles/secretmanager.admin"
    "roles/storage.admin"
    "roles/artifactregistry.admin"
    "roles/compute.admin"
    "roles/container.admin"
    "roles/cloudbuild.builds.editor"
    "roles/logging.admin"
    "roles/monitoring.admin"
)

# Optional roles that might fail in some environments
OPTIONAL_ROLES=(
    "roles/billing.user"
)

for role in "${ROLES[@]}"; do
    echo -e "  Granting ${role}..."
    retries=0
    max_retries=3
    while ! gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="${role}" \
        --quiet >/dev/null 2>&1; do
        retries=$((retries + 1))
        if [ $retries -ge $max_retries ]; then
            echo -e "${RED}Error: Failed to grant role ${role} after $max_retries attempts${NC}"
            echo -e "${YELLOW}This might be due to API propagation delays. You can try running the script again in a few minutes.${NC}"
            exit 1
        fi
        echo -e "${YELLOW}    Retry $retries/$max_retries for role ${role}...${NC}"
        sleep 5
    done
done

# Try to grant optional roles (don't fail if they can't be granted)
for role in "${OPTIONAL_ROLES[@]}"; do
    echo -e "  Granting ${role} (optional)..."
    if gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="${role}" \
        --quiet >/dev/null 2>&1; then
        echo -e "${GREEN}    Successfully granted ${role}${NC}"
    else
        echo -e "${YELLOW}    Could not grant ${role} - this may require billing admin permissions${NC}"
        echo -e "${YELLOW}    You can grant this manually later if needed${NC}"
    fi
done

echo -e "${GREEN}IAM roles granted${NC}"

# Create and download service account key
echo -e "${BLUE}Creating service account key...${NC}"

if [ -f "${KEY_FILE}" ]; then
    echo -e "${YELLOW}Key file ${KEY_FILE} already exists${NC}"
    read -p "Overwrite? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Skipping key creation${NC}"
        KEY_CREATED=false
    else
        rm -f "${KEY_FILE}"
        KEY_CREATED=true
    fi
else
    KEY_CREATED=true
fi

if [ "$KEY_CREATED" = true ]; then
    gcloud iam service-accounts keys create "${KEY_FILE}" \
        --iam-account="${SA_EMAIL}" \
        --project="${PROJECT_ID}"
    
    chmod 600 "${KEY_FILE}"
    echo -e "${GREEN}Service account key created: ${KEY_FILE}${NC}"
fi

# Create Terraform backend bucket
echo -e "${BLUE}Creating Terraform state bucket...${NC}"

BUCKET_NAME="${PROJECT_ID}-terraform-state"
BUCKET_LOCATION="us-central1"

if gsutil ls "gs://${BUCKET_NAME}" >/dev/null 2>&1; then
    echo -e "${YELLOW}Bucket gs://${BUCKET_NAME} already exists${NC}"
else
    gsutil mb -p "${PROJECT_ID}" -c STANDARD -l "${BUCKET_LOCATION}" "gs://${BUCKET_NAME}"
    gsutil versioning set on "gs://${BUCKET_NAME}"
    echo -e "${GREEN}Terraform state bucket created: gs://${BUCKET_NAME}${NC}"
fi

# Create environment file
echo -e "${BLUE}Creating environment configuration...${NC}"

cat > terraform.env << EOF
# Terraform Environment Configuration for NoETL
# Generated on $(date)

# Google Cloud Configuration
export GOOGLE_CLOUD_PROJECT="${PROJECT_ID}"
export GOOGLE_APPLICATION_CREDENTIALS="$(pwd)/${KEY_FILE}"

# Terraform Configuration
export TF_VAR_project_id="${PROJECT_ID}"
export TF_VAR_terraform_state_bucket="${BUCKET_NAME}"

# Service Account
export TF_VAR_terraform_service_account="${SA_EMAIL}"

# Default Region/Zone
export TF_VAR_region="us-central1"
export TF_VAR_zone="us-central1-a"

# Load this file with: source terraform.env
EOF

chmod 600 terraform.env

echo -e "${GREEN}Environment file created: terraform.env${NC}"

# Create .gitignore for sensitive files
echo -e "${BLUE}Creating .gitignore...${NC}"

cat > .gitignore << EOF
# Terraform
*.tfstate
*.tfstate.backup
*.tfplan
.terraform/
.terraform.lock.hcl

# Service Account Keys
*.json
terraform-sa-key.json

# Environment Files
terraform.env
.env
.env.local

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db
EOF

echo -e "${GREEN}.gitignore created${NC}"

# Display summary and next steps
echo -e "\n${GREEN}Terraform Service Account Setup Complete!${NC}\n"

echo -e "${BLUE}Summary:${NC}"
echo -e "  • Project ID: ${PROJECT_ID}"
echo -e "  • Service Account: ${SA_EMAIL}"
echo -e "  • Key File: ${KEY_FILE}"
echo -e "  • State Bucket: gs://${BUCKET_NAME}"
echo -e "  • Environment File: terraform.env"

echo -e "\n${BLUE}Next Steps:${NC}"
echo -e "  1. Load environment variables:"
echo -e "     ${YELLOW}source terraform.env${NC}"
echo -e "\n  2. Initialize Terraform:"
echo -e "     ${YELLOW}terraform init${NC}"
echo -e "\n  3. Copy and edit variables:"
echo -e "     ${YELLOW}cp terraform.tfvars.example terraform.tfvars${NC}"
echo -e "     ${YELLOW}nano terraform.tfvars${NC}"
echo -e "\n  4. Plan deployment:"
echo -e "     ${YELLOW}terraform plan${NC}"
echo -e "\n  5. Deploy infrastructure:"
echo -e "     ${YELLOW}terraform apply${NC}"

echo -e "\n${YELLOW}Important Security Notes:${NC}"
echo -e "  • Store ${KEY_FILE} securely - it provides admin access to your project"
echo -e "  • Never commit service account keys to version control"
echo -e "  • Consider using Workload Identity for production deployments"
echo -e "  • Regularly rotate service account keys"

echo -e "\n${BLUE}For more information, see the README.md file${NC}"
