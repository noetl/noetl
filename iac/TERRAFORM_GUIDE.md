# Terraform Fundamentals: A Beginner's Guide

This document provides a beginner-friendly introduction to Terraform concepts, specifically in the context of the NoETL infrastructure deployment. Use this guide to understand the Terraform files in this project.

## Table of Contents

1. [What is Terraform?](#what-is-terraform)
2. [Core Concepts](#core-concepts)
3. [Terraform File Structure](#terraform-file-structure)
4. [Resources Explained](#resources-explained)
5. [Variables and Outputs](#variables-and-outputs)
6. [State Management](#state-management)
7. [Practical Examples from NoETL](#practical-examples-from-noetl)
8. [Best Practices](#best-practices)
9. [Common Commands](#common-commands)

## What is Terraform?

Terraform is an **Infrastructure as Code (IaC)** tool that allows you to define and provision cloud infrastructure using configuration files. Instead of manually clicking through cloud provider consoles, you write code that describes what infrastructure you want, and Terraform creates it for you.

### Key Benefits:
- **Reproducible**: Same configuration creates identical infrastructure
- **Version Controlled**: Infrastructure changes are tracked in Git
- **Collaborative**: Teams can work together on infrastructure
- **Multi-Cloud**: Works with AWS, Google Cloud, Azure, and many others

## Core Concepts

### 1. **Resources**
A resource is a piece of infrastructure (like a virtual machine, database, or network). In Terraform, you declare what resources you want, and Terraform figures out how to create them.

```hcl
resource "google_compute_instance" "web_server" {
  name         = "my-web-server"
  machine_type = "e2-micro"
  zone         = "us-central1-a"
}
```

### 2. **Providers**
Providers are plugins that allow Terraform to interact with cloud platforms, SaaS providers, and APIs. For example, the Google Cloud provider lets Terraform manage Google Cloud resources.

```hcl
provider "google" {
  project = "my-project-id"
  region  = "us-central1"
}
```

### 3. **Variables**
Variables make your Terraform configuration flexible and reusable. Instead of hardcoding values, you can use variables that can be set differently for different environments.

```hcl
variable "project_id" {
  description = "The Google Cloud project ID"
  type        = string
}
```

### 4. **Outputs**
Outputs display information about your infrastructure after Terraform creates it. They're useful for getting important values like IP addresses or database connection strings.

```hcl
output "server_ip" {
  description = "The IP address of the server"
  value       = google_compute_instance.web_server.network_interface[0].access_config[0].nat_ip
}
```

### 5. **State**
Terraform keeps track of what infrastructure it has created in a **state file**. This file maps your configuration to real-world resources and helps Terraform know what changes to make.

## Terraform File Structure

Terraform files use the `.tf` extension and are written in **HCL (HashiCorp Configuration Language)**. Here's how we organize them in the NoETL project:

```
terraform/
├── main.tf           # Provider configuration and backend setup
├── variables.tf      # All variable definitions
├── infrastructure.tf # Core infrastructure (networking, database)
├── services.tf       # Application services (Cloud Run)
├── outputs.tf        # Output values
└── terraform.tfvars  # Variable values (you create this)
```

### File Purposes:

- **`main.tf`**: Defines which cloud provider to use and where to store the state file
- **`variables.tf`**: Declares all the variables you can customize
- **`infrastructure.tf`**: Creates the foundational infrastructure (networks, databases)
- **`services.tf`**: Creates the application services (web servers, workers)
- **`outputs.tf`**: Displays important information after deployment
- **`terraform.tfvars`**: Contains the actual values for your variables

## Resources Explained

A resource block has this structure:

```hcl
resource "RESOURCE_TYPE" "RESOURCE_NAME" {
  # Configuration arguments
  argument1 = "value1"
  argument2 = "value2"
  
  # Nested blocks
  nested_block {
    nested_argument = "value"
  }
}
```

### Example: Cloud Run Service

```hcl
resource "google_cloud_run_v2_service" "noetl_server" {
  name     = "noetl-server"           # What to call this service
  location = "us-central1"            # Where to deploy it
  
  template {
    containers {
      image = "gcr.io/my-project/noetl:latest"  # Which container to run
      
      resources {
        limits = {
          cpu    = "1000m"            # How much CPU to allow
          memory = "2Gi"              # How much memory to allow
        }
      }
      
      env {
        name  = "DATABASE_URL"        # Environment variable name
        value = "postgresql://..."    # Environment variable value
      }
    }
  }
}
```

### Resource Dependencies

Terraform automatically figures out the order to create resources based on dependencies:

```hcl
# This database must be created first
resource "google_sql_database_instance" "main" {
  name = "noetl-db"
  # ... configuration
}

# This service depends on the database (it references it)
resource "google_cloud_run_v2_service" "server" {
  name = "noetl-server"
  
  template {
    containers {
      env {
        name  = "DB_HOST"
        value = google_sql_database_instance.main.private_ip_address
      }
    }
  }
}
```

## Variables and Outputs

### Variable Types

```hcl
# String variable
variable "project_id" {
  description = "The Google Cloud project ID"
  type        = string
  default     = "my-default-project"
}

# Number variable
variable "worker_count" {
  description = "Number of worker instances"
  type        = number
  default     = 2
  
  validation {
    condition     = var.worker_count >= 1 && var.worker_count <= 10
    error_message = "Worker count must be between 1 and 10."
  }
}

# Boolean variable
variable "enable_monitoring" {
  description = "Whether to enable monitoring"
  type        = bool
  default     = true
}

# List variable
variable "allowed_ips" {
  description = "List of allowed IP addresses"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

# Object variable
variable "database_config" {
  description = "Database configuration"
  type = object({
    tier     = string
    disk_size = number
    backup   = bool
  })
  default = {
    tier      = "db-f1-micro"
    disk_size = 20
    backup    = true
  }
}
```

### Using Variables

In your configuration files:
```hcl
resource "google_project" "main" {
  project_id = var.project_id
}

resource "google_compute_instance" "workers" {
  count = var.worker_count
  name  = "worker-${count.index}"
}
```

In your `terraform.tfvars` file:
```hcl
project_id = "my-actual-project"
worker_count = 3
enable_monitoring = true
allowed_ips = ["203.0.113.0/24", "198.51.100.0/24"]
```

### Outputs

Outputs help you get important information after deployment:

```hcl
output "application_url" {
  description = "URL to access the NoETL application"
  value       = google_cloud_run_v2_service.noetl_server.uri
}

output "database_connection" {
  description = "Database connection information"
  value = {
    host = google_sql_database_instance.main.private_ip_address
    port = 5432
    name = google_sql_database.main.name
  }
  sensitive = true  # Don't show this in logs
}
```

## State Management

Terraform keeps track of your infrastructure in a **state file**. This file:

- Maps your configuration to real resources
- Stores metadata about your resources
- Helps Terraform plan changes efficiently

### Local vs Remote State

**Local State** (default):
```hcl
# State stored in terraform.tfstate file locally
# Good for: Learning, personal projects
# Bad for: Teams, production
```

**Remote State** (recommended):
```hcl
terraform {
  backend "gcs" {
    bucket = "my-terraform-state-bucket"
    prefix = "noetl/state"
  }
}
```

Benefits of remote state:
- **Collaboration**: Multiple people can work on the same infrastructure
- **Locking**: Prevents conflicts when multiple people run Terraform
- **Security**: State files can contain sensitive information

## Practical Examples from NoETL

Let's look at real examples from the NoETL infrastructure:

### 1. Creating a VPC Network

```hcl
# Create a custom network for our application
resource "google_compute_network" "vpc" {
  name                    = "${local.name_prefix}-vpc"
  auto_create_subnetworks = false  # We'll create subnets manually
  description             = "VPC network for NoETL ${var.environment}"
}

# Create a subnet within our network
resource "google_compute_subnetwork" "subnet" {
  name          = "${local.name_prefix}-subnet"
  ip_cidr_range = var.subnet_cidr
  region        = var.region
  network       = google_compute_network.vpc.id
  
  # Enable private Google access for Cloud SQL
  private_ip_google_access = true
}
```

### 2. Creating a Database

```hcl
# Generate a random password for the database
resource "random_password" "db_password" {
  length  = 16
  special = true
}

# Store the password securely
resource "google_secret_manager_secret" "db_password" {
  secret_id = "${local.name_prefix}-db-password"
  
  labels = local.common_labels
}

# Create the actual database instance
resource "google_sql_database_instance" "main" {
  name             = "${local.name_prefix}-db-${random_id.suffix.hex}"
  database_version = "POSTGRES_15"
  region           = var.region
  
  settings {
    tier              = var.db_tier
    availability_type = var.enable_ha ? "REGIONAL" : "ZONAL"
    disk_size         = 20
    disk_type         = "PD_SSD"
    
    # Security settings
    ip_configuration {
      ipv4_enabled    = false  # No public IP
      private_network = google_compute_network.vpc.id
    }
    
    # Backup configuration
    backup_configuration {
      enabled                        = var.enable_backup
      start_time                    = "03:00"
      point_in_time_recovery_enabled = true
      backup_retention_settings {
        retained_backups = var.backup_retention_days
      }
    }
  }
  
  deletion_protection = var.enable_deletion_protection
}
```

### 3. Creating a Cloud Run Service

```hcl
# Service account for the application
resource "google_service_account" "noetl_server" {
  account_id   = "${local.name_prefix}-server"
  display_name = "NoETL Server Service Account"
}

# Grant necessary permissions
resource "google_project_iam_member" "server_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.noetl_server.email}"
}

# The actual Cloud Run service
resource "google_cloud_run_v2_service" "noetl_server" {
  name     = "${local.name_prefix}-server"
  location = var.region
  
  template {
    scaling {
      min_instance_count = var.server_min_instances
      max_instance_count = var.server_max_instances
    }
    
    service_account = google_service_account.noetl_server.email
    
    containers {
      image = "${var.server_image_repository}:${var.server_image_tag}"
      
      resources {
        limits = {
          cpu    = var.server_cpu_limit
          memory = var.server_memory_limit
        }
      }
      
      # Environment variables
      env {
        name  = "DATABASE_HOST"
        value = google_sql_database_instance.main.private_ip_address
      }
      
      env {
        name = "DATABASE_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.db_password.secret_id
            version = "latest"
          }
        }
      }
    }
    
    # Connect to our private network
    vpc_access {
      network_interfaces {
        network    = google_compute_network.vpc.name
        subnetwork = google_compute_subnetwork.subnet.name
      }
    }
  }
}
```

## Best Practices

### 1. **File Organization**
- Split configuration into logical files (networking, compute, storage)
- Use consistent naming conventions
- Keep related resources together

### 2. **Variable Usage**
- Use variables for anything that might change between environments
- Provide good descriptions and default values
- Use validation rules where appropriate

### 3. **Naming Conventions**
```hcl
# Use prefixes to avoid naming conflicts
locals {
  name_prefix = "${var.environment}-noetl"
}

resource "google_compute_instance" "web" {
  name = "${local.name_prefix}-web-server"
}
```

### 4. **Resource Tagging/Labeling**
```hcl
# Define common labels
locals {
  common_labels = {
    environment = var.environment
    project     = "noetl"
    managed_by  = "terraform"
  }
}

# Apply to resources
resource "google_cloud_run_v2_service" "server" {
  labels = local.common_labels
  # ... other configuration
}
```

### 5. **Security**
- Never hardcode secrets in `.tf` files
- Use Secret Manager or similar services
- Set appropriate IAM permissions
- Enable deletion protection for important resources

### 6. **State Management**
- Always use remote state for production
- Enable state locking
- Regular state backups

## Common Commands

### Basic Workflow
```bash
# Initialize Terraform (download providers, setup backend)
terraform init

# See what changes Terraform will make
terraform plan

# Apply the changes
terraform apply

# Destroy all resources (be careful!)
terraform destroy
```

### Advanced Commands
```bash
# Format your code nicely
terraform fmt

# Validate your configuration
terraform validate

# Show current state
terraform show

# List all resources in state
terraform state list

# Import existing resource into Terraform
terraform import google_compute_instance.example projects/my-project/zones/us-central1-a/instances/my-instance

# Refresh state from real infrastructure
terraform refresh

# Target specific resource
terraform apply -target=google_compute_instance.web

# Use specific variables file
terraform apply -var-file=production.tfvars
```

### Working with Variables
```bash
# Set variables via command line
terraform apply -var="project_id=my-project"

# Set via environment variables
export TF_VAR_project_id="my-project"
terraform apply

# Use different tfvars files for different environments
terraform apply -var-file=development.tfvars
terraform apply -var-file=production.tfvars
```

## Troubleshooting Tips

### Common Issues:

1. **"Resource already exists"**
   - Import the existing resource: `terraform import`
   - Or delete the existing resource manually

2. **"Invalid provider configuration"**
   - Run `terraform init` to download providers
   - Check your provider version constraints

3. **"Error acquiring state lock"**
   - Another Terraform process is running
   - Or a previous run crashed, leaving a lock
   - Force unlock: `terraform force-unlock LOCK_ID`

4. **"Plan doesn't match actual state"**
   - Run `terraform refresh` to sync state
   - Check if someone made manual changes

### Debug Mode:
```bash
# Enable verbose logging
export TF_LOG=DEBUG
terraform apply

# Log to file
export TF_LOG=DEBUG
export TF_LOG_PATH=terraform.log
terraform apply
```

## Next Steps

Now that you understand the basics:

1. **Explore the NoETL Configuration**: Look at the `.tf` files in this project and identify the concepts you've learned
2. **Try Small Changes**: Modify variables in `terraform.tfvars` and see how they affect the plan
3. **Read Provider Documentation**: Check out the [Google Cloud Provider docs](https://registry.terraform.io/providers/hashicorp/google/latest/docs)
4. **Practice**: Create a simple Terraform configuration for a personal project

## Additional Resources

- [Terraform Official Tutorial](https://learn.hashicorp.com/terraform)
- [Google Cloud Provider Documentation](https://registry.terraform.io/providers/hashicorp/google/latest/docs)
- [Terraform Best Practices](https://www.terraform.io/docs/cloud/guides/recommended-practices/index.html)
- [HCL Syntax Guide](https://www.terraform.io/docs/language/syntax/configuration.html)

Remember: Infrastructure as Code is a journey. Start simple, learn incrementally, and always test your changes in a development environment first!
