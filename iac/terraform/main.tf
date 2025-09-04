# Terraform configuration for NoETL infrastructure
terraform {
  required_version = ">= 1.0"
  
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.4"
    }
  }

  backend "gcs" {
    # Bucket name will be provided via -backend-config during init
    # or set via environment variable TF_VAR_terraform_state_bucket
    prefix = "noetl/terraform/state"
  }
}

# Configure the Google Cloud Provider
provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

# Data sources
data "google_project" "project" {
  project_id = var.project_id
}

data "google_compute_default_service_account" "default" {
  project = var.project_id
}

# Random suffix for unique resource names
resource "random_id" "suffix" {
  byte_length = 4
}

# Local values
locals {
  # Environment-specific settings
  environment_settings = {
    development = {
      server_min_instances     = 0
      server_max_instances     = 2
      worker_min_instances     = 0
      worker_max_instances     = 2
      server_cpu_limit        = "1000m"
      server_memory_limit     = "2Gi"
      worker_cpu_limit        = "1000m"
      worker_memory_limit     = "2Gi"
      db_tier                 = "db-f1-micro"
      db_disk_size            = 10
      enable_ha              = false
    }
    staging = {
      server_min_instances     = 1
      server_max_instances     = 5
      worker_min_instances     = 0
      worker_max_instances     = 3
      server_cpu_limit        = "2000m"
      server_memory_limit     = "4Gi"
      worker_cpu_limit        = "2000m"
      worker_memory_limit     = "4Gi"
      db_tier                 = "db-g1-small"
      db_disk_size            = 20
      enable_ha              = false
    }
    production = {
      server_min_instances     = 2
      server_max_instances     = 10
      worker_min_instances     = 1
      worker_max_instances     = 5
      server_cpu_limit        = "4000m"
      server_memory_limit     = "8Gi"
      worker_cpu_limit        = "2000m"
      worker_memory_limit     = "4Gi"
      db_tier                 = "db-g1-small"
      db_disk_size            = 50
      enable_ha              = true
    }
  }

  # Current environment settings
  env_config = local.environment_settings[var.environment]

  # Resource naming
  name_prefix = "noetl-${var.environment}"
  
  # Common labels
  common_labels = {
    environment   = var.environment
    project       = "noetl"
    managed_by    = "terraform"
    team          = "platform"
  }

  # Container image URLs
  server_image = var.container_registry != "" ? "${var.container_registry}/noetl-server:${var.noetl_image_tag}" : "gcr.io/${var.project_id}/noetl-server:${var.noetl_image_tag}"
  worker_image = var.container_registry != "" ? "${var.container_registry}/noetl-worker:${var.noetl_image_tag}" : "gcr.io/${var.project_id}/noetl-worker:${var.noetl_image_tag}"
}
