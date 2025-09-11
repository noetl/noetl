# NoETL Infrastructure as Code

This directory contains Terraform configuration and deployment scripts for deploying NoETL to Google Cloud Platform using Cloud Run, Cloud SQL, and related services.

## Repository Structure

```
iac/
├── README.md                    # This file
├── setup-terraform-sa.sh        # Service account setup script
├── build-and-deploy.sh          # Container build and push script
├── deploy.sh                    # Terraform deployment script
└── terraform/                   # Terraform configuration
    ├── main.tf                  # Provider and backend configuration
    ├── variables.tf             # Variable definitions
    ├── infrastructure.tf        # Core infrastructure (VPC, DB, secrets)
    ├── services.tf              # Cloud Run services and IAM
    ├── outputs.tf               # Output values
    └── terraform.tfvars.example # Example configuration file
```

## Quick Start

Follow these steps to deploy NoETL to Google Cloud Platform:

### 1. Prerequisites

Ensure you have the following installed and configured:
- Google Cloud SDK (`gcloud`) 
- Terraform >= 1.0 (install via `tfenv` - see main README for details)
- Docker
- A Google Cloud Project with billing enabled
- Owner or Editor permissions on the project

### 2. Setup and Configuration

1. **Authenticate with Google Cloud:**
   ```bash
   gcloud auth login
   gcloud config set project YOUR_PROJECT_ID
   ```

2. **Create Terraform service account:**
   ```bash
   ./setup-terraform-sa.sh
   ```
   
   This automatically:
   - Enables required APIs
   - Creates service account with proper IAM roles
   - Sets up GCS backend for Terraform state
   - Generates authentication keys

3. **Initialize Terraform:**
   ```bash
   cd terraform
   source terraform.env
   terraform init
   ```

4. **Configure deployment variables:**
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   # Edit terraform.tfvars with your specific settings
   ```

### 3. Deploy

1. **Build and push container images:**
   ```bash
   ./build-and-deploy.sh --project YOUR_PROJECT_ID
   ```

2. **Deploy infrastructure (37 resources):**
   ```bash
   ./deploy.sh
   ```
   
   Or manually:
   ```bash
   terraform plan   # Review planned changes
   terraform apply  # Deploy infrastructure
   ```

3. **Access NoETL:**
   Use the server URL from the Terraform outputs to access your NoETL instance.

## Next Steps

After successful deployment:

1. **Test the deployment** by visiting the server URL
2. **Configure monitoring** in Google Cloud Console
3. **Set up custom domains** if needed
4. **Review security settings** and adjust as required
5. **Set up CI/CD pipelines** for automated deployments

## Support

- Check the [main NoETL documentation](../docs/) for application-specific guidance
- Review Google Cloud documentation for platform-specific issues
- Use the troubleshooting section below for common deployment problems

## Troubleshooting

### Common Issues

1. **Permission denied errors**: Verify that your service account has all required roles
2. **Resource quota exceeded**: Check project quotas in Google Cloud Console  
3. **Image pull errors**: Verify container images were pushed successfully
4. **Database connection issues**: Check VPC networking and firewall rules

### Getting Help

If you encounter issues:
1. Check the error logs in Google Cloud Console
2. Verify all prerequisites are met
3. Review the Terraform plan output for resource conflicts
4. Contact your platform administrator for project-level issues
