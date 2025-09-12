# How to provision NoETL IAC
Here's the step-by-step process to deploy NoETL infrastructure:
## Prerequisites
1. **Install Required Tools**:
``` bash
   # Install Google Cloud SDK
   curl https://sdk.cloud.google.com | bash
   exec -l $SHELL  # Restart shell
   
   # Install Terraform (using tfenv for version management)
   brew install tfenv  # On macOS
   tfenv install 1.10.3
   tfenv use 1.10.3
   
   # Install Docker
   # Follow Docker installation guide for  OS
```
1. **Set Up Google Cloud**:
``` bash
   # Authenticate with Google Cloud
   gcloud auth login
   
   # Set google project 
   gcloud config set project GOOGLE_PROJECT_ID
   
   # Enable billing on  project 
   # This must be done via the Google Cloud Console
```
## Execution Steps
### Step 1: Navigate to IAC Directory
``` bash
cd iac
```
### Step 2: Validate  Setup
``` bash
# Run the validation script to check prerequisites
./validate-deployment.sh
```
This checks if all tools are installed and configured correctly.
### Step 3: Set Up Service Account and Permissions
``` bash
# This creates a service account with all necessary permissions
./setup-terraform-sa.sh
```
**What this does**:
- Enables required Google Cloud APIs (Cloud Run, Cloud SQL, etc.)
- Creates a service account for Terraform
- Grants necessary IAM roles
- Creates authentication keys
- Sets up Terraform state storage bucket
- Generates configuration file `terraform.env`

**Expected output**: Green success messages and next steps instructions.
### Step 4: Configure Terraform Variables
``` bash
cd terraform

# Copy the example configuration
cp terraform.tfvars.example terraform.tfvars

# Edit with  specific settings
nano terraform.tfvars  # or use  preferred editor
```
**Key settings to configure**:
- :  Google Cloud project ID `project_id`
- `environment`: "development", "staging", or "production"
- `region`:  preferred region (default: us-central1)
- Worker counts and resource limits as needed

### Step 5: Initialize Terraform
``` bash
# Load environment variables
source terraform.env

# Initialize Terraform with backend configuration
terraform init
```
### Step 6: Build and Push Container Images
``` bash
# Return to iac directory
cd ..

# Build NoETL Docker images and push to Google Container Registry
./build-and-deploy.sh --project GOOGLE_PROJECT_ID
```
**What this does**:
- Builds NoETL server and worker Docker images
- Pushes images to Google Container Registry
- Makes images available for Cloud Run deployment

### Step 7: Deploy Infrastructure
``` bash
# Deploy using the automated script
./deploy.sh
```
**Or manually with more control**:
``` bash
cd terraform
source terraform.env

# Review what will be created (37 resources)
terraform plan

# Deploy the infrastructure
terraform apply
```
**Expected deployment time**: 10-15 minutes
### Step 8: Access  NoETL Instance
After successful deployment, Terraform will output the server URL:
``` bash
# View all outputs
terraform output

# Get just the server URL
terraform output noetl_server_url
```
Visit the URL to access NoETL web interface.
## Quick Execution (One-Command Approach)
For experienced users, you can chain commands:
``` bash
cd iac && \
./setup-terraform-sa.sh && \
cd terraform && \
source terraform.env && \
terraform init && \
cd .. && \
./build-and-deploy.sh --project GOOGLE_PROJECT_ID && \
./deploy.sh
```
## Verification Steps
1. **Check Cloud Run Services**:
``` bash
   gcloud run services list --region=us-central1
```
1. **Verify Database**:
``` bash
   gcloud sql instances list
```
1. **Test the Application**:
    - Visit the server URL from Terraform outputs
    - Check that the NoETL web interface loads
    - Verify worker services are healthy

## Environment-Specific Execution
### Development Environment
``` bash
# In terraform.tfvars, set:
environment = "development"
cpu_worker_count = 1
enable_debug_mode = true
```
### Production Environment
``` bash
# In terraform.tfvars, set:
environment = "production"
cpu_worker_count = 3
enable_db_ha = true
backup_retention_days = 30
```
## Troubleshooting Common Issues
1. **Permission Errors**: Re-run `./setup-terraform-sa.sh`
2. **Image Build Failures**: Check Docker is running and you have project access
3. **Terraform Errors**: Run `terraform plan` first to see what will change
4. **Quota Issues**: Check Google Cloud Console for quota limits

## Clean Up (When Done Testing)
``` bash
cd terraform
source terraform.env
terraform destroy
```
**Total execution time**: 20-25 minutes for first-time setup, 10-15 minutes for subsequent deployments.
The process is designed to be mostly automated - you mainly need to configure google project settings and let the scripts handle the complex cloud resource creation.
