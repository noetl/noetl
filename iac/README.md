# NoETL Infrastructure as Code (IaC)

This directory contains Infrastructure as Code (IaC) configurations f### 3. Deploy Infrastructure

1. **Build and push container images:**
   ```bash
   # From the iac directory
   ./build-and-deploy.sh --project GOOGLE_PROJECT_ID
   ```

2. **Deploy the infrastructure:**
   ```bash
   ./deploy.sh
   ```
   
   Or manually with Terraform:
   ```bash
   cd terraform
   source terraform.env
   terraform plan
   terraform apply
   ```

3. **Access your NoETL instance:**
   The deployment will output the server URL. Visit it to access the NoETL UI.ETL to Google Cloud Platform using Terraform.

## Current Status

- **Service Account Setup**: Completed and tested  
- **Terraform Configuration**: Complete with 37 cloud resources  
- **Terraform Initialization**: Working with GCS backend  
- **Infrastructure Plan**: Validated and ready for deployment  
- **Container Images**: Need to be built before Cloud Run deployment  
- **Infrastructure Deployment**: Ready to deploy once images are built  

### What Gets Deployed

When you run `terraform apply`, the following infrastructure will be created:

**Core Services:**
- 1x NoETL Server (Cloud Run)
- 2x CPU Workers (Cloud Run) 
- 0x GPU Workers (disabled by default)

**Database & Storage:**
- 1x PostgreSQL 15 instance (Cloud SQL)
- 1x Cloud Storage bucket
- Auto-generated secure passwords in Secret Manager

**Networking & Security:**
- Private VPC with subnet and firewall rules
- Cloud NAT for outbound connectivity
- Service accounts with least-privilege IAM
- Private database connectivity with no public access

**Monitoring & Logging:**
- Cloud Logging integration
- Cloud Monitoring and Tracing
- Health checks for all services

The NoETL infrastructure deploys a cloud-native solution on Google Cloud Platform:

### Core Components

- **NoETL Server**: Cloud Run service hosting the main API server and web UI
- **NoETL CPU Workers**: Scalable Cloud Run services for CPU-intensive workloads (2 instances by default)
- **NoETL GPU Workers**: Optional Cloud Run services for GPU-intensive workloads
- **Cloud SQL PostgreSQL**: Managed database with automated backups and high availability options
- **VPC Networking**: Private network with Cloud NAT for secure outbound connectivity
- **Secret Manager**: Secure storage for database passwords and API keys
- **Cloud Storage**: Bucket for NoETL data with lifecycle management
- **IAM & Security**: Service accounts with least-privilege access

### Infrastructure Resources

The Terraform configuration creates **37 cloud resources** including:

- **Networking**: VPC, subnet, firewall rules, Cloud NAT, private IP peering
- **Database**: PostgreSQL 15 instance with private IP, automated backups, point-in-time recovery
- **Services**: Auto-scaling Cloud Run services with health checks and monitoring
- **Security**: Service accounts, IAM roles, Secret Manager secrets, encrypted storage
- **Monitoring**: Cloud Logging, Monitoring, and Tracing integration

### Environment Configuration

The infrastructure supports multiple environments (development, staging, production) with:
- Environment-specific resource sizing and scaling limits
- Configurable database tiers and backup retention
- Optional high availability and deletion protection for production
- Customizable networking and security settings

## Prerequisites

1. **Google Cloud Project**: Active GCP project with billing enabled
2. **Terraform**: Terraform >= 1.0 installed locally (see [Terraform Installation](#terraform-installation) below)
3. **gcloud CLI**: Google Cloud SDK installed and authenticated
4. **Docker**: For building and pushing container images
5. **Domain** : Optional, for custom domain setup

### Terraform Installation

We recommend using `tfenv` to manage Terraform versions:

#### Install tfenv

**On macOS:**
```bash
brew install tfenv
```

**On Linux:**
```bash
git clone https://github.com/tfutils/tfenv.git ~/.tfenv
echo 'export PATH="$HOME/.tfenv/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

#### Install and Use Terraform

```bash
# List available Terraform versions
tfenv list-remote

# Install the latest Terraform version
tfenv install latest

# Or install a specific version (recommended for production)
tfenv install 1.10.3

# Set the Terraform version to use
tfenv use 1.10.3

# Verify installation
terraform version
```

#### Check Your Current Terraform Setup

```bash
# List installed versions
tfenv list

# Shows output like:
# * 1.10.3 (set by /opt/homebrew/Cellar/tfenv/3.0.0/version)
#   1.2.8
```

The `*` indicates the currently active version.

## Quick Start

### 1. Prerequisites

Before you begin, ensure you have:

- Google Cloud SDK `gcloud` installed and configured
- Terraform >= 1.0 installed (see [Terraform Installation](#terraform-installation) above)
- Docker installed to build images
- A Google Cloud Project with billing enabled
- Owner or Editor permissions on the project

### 2. Initial Setup

1. **Create a service account for Terraform:**
   ```bash
   ./setup-terraform-sa.sh
   ```
   
   This script will:
   - Enable required Google Cloud APIs (Cloud Run, Cloud SQL, Secret Manager, etc.)
   - Create a service account with necessary IAM roles
   - Generate and download a service account key
   - Create a GCS bucket for Terraform state storage
   - Set up environment variables in `terraform.env`

2. **Configure Terraform:**
   ```bash
   cd terraform
   source terraform.env  # Load service account credentials
   terraform init        # Initialize Terraform with GCS backend
   ```

3. **Configure your deployment:**
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   # Edit terraform.tfvars with your project settings
   # The project_id should already be set correctly by the setup script
   ```

### 3. Deploy Infrastructure

**Important**: You must build and push Docker images before deploying Cloud Run services.

1. **Build and push container images:**
   ```bash
   # From the iac directory
   ./build-and-deploy.sh --project GOOGLE_PROJECT_ID
   ```

2. **Plan and deploy the infrastructure:**
   ```bash
   ./deploy.sh
   ```
   
   Or manually with Terraform:
   ```bash
   cd terraform
   source terraform.env
   terraform plan    # Review what will be created (37 resources)
   terraform apply   # Deploy the infrastructure
   ```

3. **Access your NoETL instance:**
   The deployment will output the server URL. Visit it to access the NoETL UI.

### 4. Verify Deployment

After successful deployment, you can verify the setup:

```bash
# Check Cloud Run services
gcloud run services list --region=us-central1

# Check database instance
gcloud sql instances list

# View Terraform outputs
terraform output
```

## Scripts Overview

### build-and-deploy.sh
Builds NoETL Docker images and pushes them to Google Container Registry.

**Usage:**
```bash
./build-and-deploy.sh [OPTIONS]

Options:
  -p, --project PROJECT_ID    Google Cloud project ID
  -r, --region REGION         Google Cloud region (default: us-central1)
  -t, --tag TAG               Image tag (default: latest)
  -h, --help                  Show help message

Examples:
  ./build-and-deploy.sh --project noetl-project --tag v1.0.0
  PROJECT_ID=noetl-project ./build-and-deploy.sh
```

### deploy.sh
Deploys NoETL infrastructure using Terraform with validation and error handling.

**Usage:**
```bash
./deploy.sh [OPTIONS]

Options:
  -f, --tfvars FILE           Path to Terraform variables file
  -y, --auto-approve          Skip interactive approval of plan
  -d, --destroy               Destroy infrastructure instead of creating
  -p, --plan-only             Only run terraform plan
  -i, --init-only             Only run terraform init
  -h, --help                  Show help message

Examples:
  ./deploy.sh                          # Interactive deployment with terraform.tfvars
  ./deploy.sh -f dev.tfvars -y         # Deploy with dev.tfvars, auto-approve
  ./deploy.sh --plan-only              # Only show the plan
  ./deploy.sh --destroy -y             # Destroy infrastructure with auto-approve
```

### setup-terraform-sa.sh
Creates and configures a service account for Terraform with proper IAM roles.

### 4. Build and Deploy Application
- Build and push Docker images:
```bash
./build-and-push.sh
```

- Update Cloud Run services with new images:
```bash
terraform apply -var="deploy_timestamp=$(date +%s)"
```

## Configuration

### Required Variables

Edit `terraform.tfvars` with google project-specific values:

```hcl
# GCP Project Configuration
project_id = "google-project-id"
region     = "us-central1"
zone       = "us-central1-a"

# NoETL Configuration
noetl_image_tag = "latest"
environment     = "production"

# Database Configuration
db_name     = "noetl"
db_user     = "noetl"
db_password = "noetl-secure-password"

# Networking
enable_custom_domain = false
domain_name         = "noetl.io"

# Workers Configuration
cpu_worker_count = 2
gpu_worker_count = 1
enable_gpu_workers = false
```

### Environment Variables

The deployment supports environment-specific configurations:

- `development`: Single instance, minimal resources
- `staging`: Multiple workers, moderate resources  
- `production`: Auto-scaling, high availability

## Services Deployed

### NoETL Server
- **URL**: Automatically generated Cloud Run URL
- **Purpose**: Main API server, web UI, job orchestration
- **Resources**: 2 vCPU, 4GB RAM (configurable)
- **Scaling**: 0-10 instances (configurable)

### CPU Workers  
- **Count**: Configurable (default: 2)
- **Purpose**: Execute CPU-intensive playbook tasks
- **Resources**: 2 vCPU, 4GB RAM (configurable)
- **Scaling**: 0-5 instances per worker

### GPU Workers (Optional)
- **Count**: Configurable (default: 1) 
- **Purpose**: Execute GPU-intensive ML/AI tasks
- **Resources**: 4 vCPU, 8GB RAM + GPU (configurable)
- **Scaling**: 0-3 instances per worker

### Cloud SQL PostgreSQL
- **Instance**: db-g1-small (configurable)
- **Storage**: 20GB SSD (auto-expanding)
- **Backups**: Daily automated backups
- **High Availability**: Optional (production recommended)

## Monitoring and Logging

The deployment includes:

- **Cloud Logging**: Centralized log aggregation
- **Cloud Monitoring**: Metrics and alerting
- **Health Checks**: Service availability monitoring
- **Error Reporting**: Automatic error tracking

Access monitoring:
```bash
# View logs
gcloud logging read "resource.type=cloud_run_revision"

# View metrics in Cloud Console
gcloud console url --format="value(url)"
```

## Scaling and Performance

### Auto-scaling Configuration

```hcl
# In terraform.tfvars
server_min_instances = 1
server_max_instances = 10
worker_min_instances = 0
worker_max_instances = 5

# Resource allocation
server_cpu_limit = "2000m"
server_memory_limit = "4Gi"
worker_cpu_limit = "2000m" 
worker_memory_limit = "4Gi"
```

### Manual Scaling

```bash
# Scale server instances
gcloud run services update noetl-server \
  --max-instances=20 \
  --region=us-central1

# Scale worker instances  
gcloud run services update noetl-worker-cpu-1 \
  --max-instances=10 \
  --region=us-central1
```

## Security

### IAM Roles

The deployment creates service accounts with minimal required permissions:

- **NoETL Server**: Cloud SQL client, Secret Manager accessor
- **Workers**: Cloud Storage object admin, logging writer
- **Terraform**: Admin roles for resource creation

### Network Security

- **Private IP**: Services use private networking
- **Firewall Rules**: Restrictive ingress/egress rules
- **VPC**: Isolated network environment
- **Cloud NAT**: Outbound internet access without public IPs

### Secrets Management

Sensitive data is stored in Google Secret Manager:

```bash
# Create secrets
gcloud secrets create noetl-db-password --data-file=- <<< "noetl-db-password"
gcloud secrets create noetl-api-key --data-file=- <<< "noetl-api-key"

# Grant access to service accounts
gcloud secrets add-iam-policy-binding noetl-db-password \
  --member="serviceAccount:noetl-server@project.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

## Troubleshooting

### Common Issues and Solutions

#### Service Account Setup
**Issue**: `ERROR: Service account terraform-noetl@project.iam.gserviceaccount.com does not exist`  
**Solution**: The script now includes retry logic and propagation delays. If it still fails, wait 2-3 minutes and re-run the script.

**Issue**: `Could not grant roles/billing.user`  
**Solution**: This role is now optional. The deployment will work without it. You can grant it manually if needed for billing operations.

#### Terraform Initialization
**Issue**: `bucket doesn't exist`  
**Solution**: The setup script creates the bucket automatically. Ensure you ran `./setup-terraform-sa.sh` successfully first.

**Issue**: `No valid credential sources found`  
**Solution**: Run `source terraform.env` to load the service account credentials before using Terraform.

#### Container Images
**Issue**: Cloud Run deployment fails with "image not found"  
**Solution**: Run `./build-and-deploy.sh --project GOOGLE_PROJECT_ID` before `terraform apply`.

#### Variable Warnings
**Issue**: `Value for undeclared variable` warnings  
**Solution**: These are warnings, not errors. The deployment will work. You can ignore them or remove unused variables from `terraform.tfvars`.

### Getting Help

1. **Check Terraform plan**: Always run `terraform plan` to see what will be created/changed
2. **Review logs**: Use `gcloud logging read` to check service logs
3. **Verify authentication**: Ensure `source terraform.env` was run and credentials are valid
4. **Check API enablement**: Verify all required APIs are enabled in your project

## Maintenance

### Updates

```bash
# Update infrastructure
terraform plan
terraform apply

# Update application
./build-and-push.sh
terraform apply -var="deploy_timestamp=$(date +%s)"
```

### Backups

- **Database**: Automated daily backups with 7-day retention
- **Configuration**: Terraform state stored in Cloud Storage
- **Disaster Recovery**: Cross-region backup replication (optional)

### Monitoring Health

```bash
# Check service health
gcloud run services describe noetl-server --region=us-central1

# View recent deployments
gcloud run revisions list --service=noetl-server --region=us-central1

# Check logs for errors
gcloud logging read "resource.type=cloud_run_revision AND severity>=ERROR" --limit=50
```

## Troubleshooting

### Common Issues

1. **Service Account Permissions**
   ```bash
   # Check permissions
   gcloud iam service-accounts get-iam-policy terraform@project.iam.gserviceaccount.com
   ```

2. **Database Connection**
   ```bash
   # Test database connectivity
   gcloud sql connect noetl-db --user=noetl
   ```

3. **Image Build Failures**
   ```bash
   # Build locally and test
   docker build -t noetl:test -f docker/noetl/dev/Dockerfile .
   docker run -it noetl:test /bin/bash
   ```

4. **Cloud Run Deployment Issues**
   ```bash
   # Check revision status
   gcloud run revisions describe REVISION_NAME --region=us-central1
   ```

### Support

For issues and support:
- Check the [NoETL Documentation](../docs/)
- Review [Cloud Run Documentation](https://cloud.google.com/run/docs)
- File issues in the project repository

## Cost Optimization

### Resource Sizing

- **Development**: 1 vCPU, 2GB RAM per service
- **Staging**: 2 vCPU, 4GB RAM per service  
- **Production**: 4 vCPU, 8GB RAM per service

### Cost Monitoring

```bash
# View current costs
gcloud billing budgets list

# Set up billing alerts
gcloud alpha billing budgets create \
  --billing-account=BILLING_ACCOUNT_ID \
  --display-name="NoETL Budget" \
  --budget-amount=1000USD
```

## Next Steps

1. **Configure DNS**: Point domain to the Cloud Run URL
2. **Set up CI/CD**: Automate deployments with Cloud Build
3. **Monitor Performance**: Set up custom dashboards and alerts
4. **Security Review**: Conduct security assessment and penetration testing
5. **Load Testing**: Validate performance under expected load
