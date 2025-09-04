# NoETL Infrastructure as Code (IaC)

This directory contains Infrastructure as Code (IaC) configurations for deploying NoETL to Google Cloud Platform using Terraform.

## Architecture

The Terraform configuration deploys:

- **NoETL Server**: Cloud Run service for the main API server
- **NoETL CPU Workers**: Cloud Run services for CPU-intensive workloads
- **NoETL GPU Workers**: Cloud Run services for GPU-intensive workloads (optional)
- **Cloud SQL PostgreSQL**: Managed database for NoETL metadata
- **Container Registry**: For storing Docker images
- **Service Accounts**: With appropriate IAM roles
- **Networking**: VPC, subnets, and firewall rules
- **Secrets**: For storing sensitive configuration

## Prerequisites

1. **Google Cloud Project**: Active GCP project with billing enabled
2. **Terraform**: Terraform >= 1.0 installed locally
3. **gcloud CLI**: Google Cloud SDK installed and authenticated
4. **Docker**: For building and pushing container images
5. **Domain** : Optional, for custom domain setup

## Quick Start

### 1. Prerequisites

Before you begin, ensure you have:

- Google Cloud SDK `gcloud` installed and configured
- Terraform >= 1.0 installed
- Docker installed to build images
- A Google Cloud Project with billing enabled
- Owner or Editor permissions on the project

### 2. Initial Setup

1. **Create a service account for Terraform:**
   ```bash
   ./setup-terraform-sa.sh
   ```

2. **Configure Terraform backend:**
   ```bash
   cd terraform
   # Edit main.tf to set backend bucket name
   # The bucket will be created automatically if it doesn't exist
   ```

3. **Configure your deployment:**
   ```bash
   cp terraform/terraform.tfvars.example terraform/terraform.tfvars
   # Edit terraform.tfvars with project settings
   ```

### 3. Deploy Infrastructure

1. **Build and push container images:**
   ```bash
   # From the iac directory
   ./build-and-deploy.sh --project PROJECT_ID
   ```

2. **Deploy the infrastructure:**
   ```bash
   ./deploy.sh
   ```

3. **Access your NoETL instance:**
   The deployment will output the server URL. Visit it to access the NoETL UI.

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
