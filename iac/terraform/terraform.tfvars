# Example Terraform variables file for NoETL deployment
# Copy this file to terraform.tfvars and modify the values as needed

# Project Configuration
project_id = "mestumre-dev-host"
region     = "us-central1"
zone       = "us-central1-a"

# Environment Configuration  
environment = "dev"  # Options: dev, staging, prod

# Database Configuration
db_name     = "noetl"
db_user     = "noetl_user"
db_tier     = "db-f1-micro"  # Options: db-f1-micro, db-g1-small, db-n1-standard-1, etc.
enable_ha   = false  # Set to true for production environments

# Container Images
server_image_tag = "latest"
worker_image_tag = "latest"
# server_image_repository = "gcr.io/your-project/noetl-server"  # Uncomment to override
# worker_image_repository = "gcr.io/your-project/noetl-worker"  # Uncomment to override

# Worker Configuration
cpu_worker_count   = 2
enable_gpu_workers = false
gpu_worker_count   = 1

# Resource Limits (leave empty to use environment defaults)
server_cpu_limit    = ""  # e.g., "1000m"
server_memory_limit = ""  # e.g., "2Gi"
worker_cpu_limit    = ""  # e.g., "2000m"
worker_memory_limit = ""  # e.g., "4Gi"

# Auto-scaling Configuration
server_min_instances = null  # null uses environment default
server_max_instances = null  # null uses environment default
worker_min_instances = null  # null uses environment default
worker_max_instances = null  # null uses environment default

# Networking Configuration
vpc_cidr           = "10.0.0.0/16"
subnet_cidr        = "10.0.1.0/24"
enable_private_ip  = true
authorized_networks = [
  {
    name  = "office-network"
    value = "203.0.113.0/24"  # Replace with your office IP range
  }
]

# Security Configuration
enable_deletion_protection = false  # Set to true for production
enable_backup             = true
backup_retention_days     = 7

# Feature Flags
enable_monitoring   = true
enable_debug_mode   = false
enable_api_auth     = true

# Logging Configuration
log_level = "INFO"  # Options: DEBUG, INFO, WARNING, ERROR

# Labels (optional)
# labels = {
#   cost_center = "engineering"
#   team        = "data-platform"
#   project     = "noetl"
# }
