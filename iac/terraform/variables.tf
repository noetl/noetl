variable "project_id" {
  description = "The GCP project ID"
  type        = string
}

variable "region" {
  description = "The GCP region for resources"
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "The GCP zone for resources"
  type        = string
  default     = "us-central1-a"
}

variable "environment" {
  description = "Environment name (development, staging, production)"
  type        = string
  default     = "development"
  
  validation {
    condition     = contains(["development", "staging", "production"], var.environment)
    error_message = "Environment must be one of: development, staging, production."
  }
}

# Container Configuration
variable "noetl_image_tag" {
  description = "Docker image tag for NoETL containers"
  type        = string
  default     = "latest"
}

variable "container_registry" {
  description = "Container registry URL (defaults to GCR if empty)"
  type        = string
  default     = ""
}

# Database Configuration
variable "db_name" {
  description = "Cloud SQL database name"
  type        = string
  default     = "noetl"
}

variable "db_user" {
  description = "Cloud SQL database user"
  type        = string
  default     = "noetl"
}

variable "db_password" {
  description = "Cloud SQL database password (leave empty to auto-generate)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "db_tier" {
  description = "Cloud SQL instance tier"
  type        = string
  default     = ""
}

variable "db_disk_size" {
  description = "Cloud SQL disk size in GB"
  type        = number
  default     = 20
}

variable "enable_db_ha" {
  description = "Enable high availability for Cloud SQL"
  type        = bool
  default     = false
}

# Networking Configuration
variable "enable_custom_domain" {
  description = "Enable custom domain configuration"
  type        = bool
  default     = false
}

variable "domain_name" {
  description = "Custom domain name for NoETL server"
  type        = string
  default     = ""
}

variable "enable_ssl" {
  description = "Enable SSL/TLS certificates"
  type        = bool
  default     = true
}

# Worker Configuration
variable "cpu_worker_count" {
  description = "Number of CPU worker instances"
  type        = number
  default     = 2
  
  validation {
    condition     = var.cpu_worker_count >= 0 && var.cpu_worker_count <= 10
    error_message = "CPU worker count must be between 0 and 10."
  }
}

variable "gpu_worker_count" {
  description = "Number of GPU worker instances"
  type        = number
  default     = 0
  
  validation {
    condition     = var.gpu_worker_count >= 0 && var.gpu_worker_count <= 5
    error_message = "GPU worker count must be between 0 and 5."
  }
}

variable "enable_gpu_workers" {
  description = "Enable GPU worker instances"
  type        = bool
  default     = false
}

# Resource Limits (Override environment defaults)
variable "server_min_instances" {
  description = "Minimum number of server instances"
  type        = number
  default     = null
}

variable "server_max_instances" {
  description = "Maximum number of server instances"
  type        = number
  default     = null
}

variable "worker_min_instances" {
  description = "Minimum number of worker instances"
  type        = number
  default     = null
}

variable "worker_max_instances" {
  description = "Maximum number of worker instances"
  type        = number
  default     = null
}

variable "server_cpu_limit" {
  description = "CPU limit for server instances"
  type        = string
  default     = ""
}

variable "server_memory_limit" {
  description = "Memory limit for server instances"
  type        = string
  default     = ""
}

variable "worker_cpu_limit" {
  description = "CPU limit for worker instances"
  type        = string
  default     = ""
}

variable "worker_memory_limit" {
  description = "Memory limit for worker instances"
  type        = string
  default     = ""
}

# Security Configuration
variable "allowed_ingress_cidrs" {
  description = "CIDR blocks allowed to access NoETL services"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "enable_binary_authorization" {
  description = "Enable Binary Authorization for container images"
  type        = bool
  default     = false
}

variable "enable_istio" {
  description = "Enable Istio service mesh"
  type        = bool
  default     = false
}

# Monitoring and Logging
variable "enable_cloud_trace" {
  description = "Enable Cloud Trace for distributed tracing"
  type        = bool
  default     = true
}

variable "enable_cloud_profiler" {
  description = "Enable Cloud Profiler for performance analysis"
  type        = bool
  default     = false
}

variable "log_level" {
  description = "Application log level"
  type        = string
  default     = "INFO"
  
  validation {
    condition     = contains(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], var.log_level)
    error_message = "Log level must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL."
  }
}

# Backup and Disaster Recovery
variable "enable_cross_region_backup" {
  description = "Enable cross-region backup for disaster recovery"
  type        = bool
  default     = false
}

variable "backup_retention_days" {
  description = "Number of days to retain database backups"
  type        = number
  default     = 7
}

# Cost Optimization
variable "enable_preemptible_workers" {
  description = "Use preemptible instances for workers to reduce costs"
  type        = bool
  default     = false
}

variable "enable_autoscaling" {
  description = "Enable automatic scaling based on metrics"
  type        = bool
  default     = true
}

# Development/Testing
variable "deploy_timestamp" {
  description = "Deployment timestamp for triggering updates"
  type        = string
  default     = ""
}

variable "enable_debug_mode" {
  description = "Enable debug mode for development"
  type        = bool
  default     = false
}

# Terraform State
variable "terraform_state_bucket" {
  description = "GCS bucket for Terraform state"
  type        = string
  default     = ""
}

variable "terraform_service_account" {
  description = "Service account email for Terraform"
  type        = string
  default     = ""
}

# Feature Flags
variable "enable_experimental_features" {
  description = "Enable experimental NoETL features"
  type        = bool
  default     = false
}

variable "enable_metrics_dashboard" {
  description = "Deploy custom metrics dashboard"
  type        = bool
  default     = true
}

# External Dependencies
variable "external_postgres_host" {
  description = "External PostgreSQL host (if not using Cloud SQL)"
  type        = string
  default     = ""
}

variable "external_postgres_port" {
  description = "External PostgreSQL port"
  type        = number
  default     = 5432
}

variable "external_redis_host" {
  description = "External Redis host for caching"
  type        = string
  default     = ""
}

variable "external_redis_port" {
  description = "External Redis port"
  type        = number
  default     = 6379
}
