# Terraform variables file for NoETL deployment
# Configured for mestumre-dev-host project

# Project Configuration
project_id = "mestumre-dev-host"
region     = "us-central1"
zone       = "us-central1-a"

# Environment Configuration  
environment = "development"  # Options: development, staging, production

# Database Configuration
db_name     = "noetl"
db_user     = "noetl"
db_tier     = ""  # Will use environment default (db-f1-micro for development)
db_disk_size = 20
enable_db_ha = false  # Set to true for production environments

# Container Images
noetl_image_tag = "latest"
container_registry = ""  # Will use default GCR

# Worker Configuration
cpu_worker_count   = 2
enable_gpu_workers = false
gpu_worker_count   = 0

# Resource Limits (empty strings will use environment defaults)
server_cpu_limit    = ""  # e.g., "1000m"
server_memory_limit = ""  # e.g., "2Gi"
worker_cpu_limit    = ""  # e.g., "2000m"
worker_memory_limit = ""  # e.g., "4Gi"

# Auto-scaling Configuration (null uses environment defaults)
server_min_instances = null
server_max_instances = null
worker_min_instances = null
worker_max_instances = null

# Security Configuration
allowed_ingress_cidrs = ["0.0.0.0/0"]  # Restrict this for production

# Monitoring and Logging
enable_cloud_trace = true
log_level = "INFO"  # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL

# Backup Configuration
backup_retention_days = 7

# Development Configuration
enable_debug_mode = true
deploy_timestamp = ""

# Feature Flags
enable_experimental_features = false
enable_metrics_dashboard = true
