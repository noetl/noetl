# Service accounts for NoETL components
resource "google_service_account" "noetl_server" {
  account_id   = "${local.name_prefix}-server"
  display_name = "NoETL Server Service Account"
  description  = "Service account for NoETL server running in Cloud Run"
}

resource "google_service_account" "noetl_worker" {
  account_id   = "${local.name_prefix}-worker"
  display_name = "NoETL Worker Service Account"
  description  = "Service account for NoETL workers running in Cloud Run"
}

# IAM roles for server service account
resource "google_project_iam_member" "server_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.noetl_server.email}"
}

resource "google_project_iam_member" "server_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.noetl_server.email}"
}

resource "google_project_iam_member" "server_storage_admin" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.noetl_server.email}"
}

resource "google_project_iam_member" "server_logging_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.noetl_server.email}"
}

resource "google_project_iam_member" "server_monitoring_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.noetl_server.email}"
}

resource "google_project_iam_member" "server_trace_agent" {
  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${google_service_account.noetl_server.email}"
}

resource "google_project_iam_member" "server_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.noetl_server.email}"
}

# IAM roles for worker service account
resource "google_project_iam_member" "worker_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.noetl_worker.email}"
}

resource "google_project_iam_member" "worker_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.noetl_worker.email}"
}

resource "google_project_iam_member" "worker_storage_admin" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.noetl_worker.email}"
}

resource "google_project_iam_member" "worker_logging_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.noetl_worker.email}"
}

resource "google_project_iam_member" "worker_monitoring_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.noetl_worker.email}"
}

resource "google_project_iam_member" "worker_trace_agent" {
  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${google_service_account.noetl_worker.email}"
}

# Cloud Run service for NoETL server
resource "google_cloud_run_v2_service" "noetl_server" {
  name     = "${local.name_prefix}-server"
  location = var.region
  
  labels = local.common_labels

  template {
    labels = local.common_labels
    
    scaling {
      min_instance_count = var.server_min_instances != null ? var.server_min_instances : local.env_config.server_min_instances
      max_instance_count = var.server_max_instances != null ? var.server_max_instances : local.env_config.server_max_instances
    }

    service_account = google_service_account.noetl_server.email

    containers {
      image = local.server_image

      resources {
        limits = {
          cpu    = var.server_cpu_limit != "" ? var.server_cpu_limit : local.env_config.server_cpu_limit
          memory = var.server_memory_limit != "" ? var.server_memory_limit : local.env_config.server_memory_limit
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      ports {
        container_port = 8082
      }

      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }

      env {
        name  = "NOETL_HOST"
        value = "0.0.0.0"
      }

      env {
        name  = "NOETL_PORT"
        value = "8082"
      }

      env {
        name  = "NOETL_SERVER"
        value = "uvicorn"
      }

      env {
        name  = "NOETL_RUN_MODE"
        value = "server"
      }

      env {
        name  = "LOG_LEVEL"
        value = var.log_level
      }

      env {
        name  = "POSTGRES_HOST"
        value = google_sql_database_instance.main.private_ip_address
      }

      env {
        name  = "POSTGRES_PORT"
        value = "5432"
      }

      env {
        name  = "POSTGRES_DB"
        value = var.db_name
      }

      env {
        name  = "POSTGRES_USER"
        value = var.db_user
      }

      env {
        name = "POSTGRES_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.db_password.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "NOETL_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.noetl_api_key.secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }

      env {
        name  = "NOETL_ENABLE_UI"
        value = "true"
      }

      env {
        name  = "NOETL_SCHEMA_VALIDATE"
        value = "true"
      }

      env {
        name  = "NOETL_DEBUG"
        value = var.enable_debug_mode ? "true" : "false"
      }

      # Health check configuration
      startup_probe {
        http_get {
          path = "/health"
          port = 8082
        }
        initial_delay_seconds = 10
        timeout_seconds      = 5
        period_seconds       = 10
        failure_threshold    = 3
      }

      liveness_probe {
        http_get {
          path = "/health"
          port = 8082
        }
        initial_delay_seconds = 30
        timeout_seconds      = 5
        period_seconds       = 30
        failure_threshold    = 3
      }
    }

    vpc_access {
      network_interfaces {
        network    = google_compute_network.vpc.name
        subnetwork = google_compute_subnetwork.subnet.name
        tags       = ["${local.name_prefix}-server", "${local.name_prefix}-internal"]
      }
      egress = "ALL_TRAFFIC"
    }
  }

  traffic {
    percent = 100
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
  }

  depends_on = [google_sql_database_instance.main]
}

# Cloud Run services for CPU workers
resource "google_cloud_run_v2_service" "noetl_worker_cpu" {
  count    = var.cpu_worker_count
  name     = "${local.name_prefix}-worker-cpu-${count.index + 1}"
  location = var.region
  
  labels = merge(local.common_labels, {
    worker_type = "cpu"
    worker_id   = tostring(count.index + 1)
  })

  template {
    labels = merge(local.common_labels, {
      worker_type = "cpu"
      worker_id   = tostring(count.index + 1)
    })
    
    scaling {
      min_instance_count = var.worker_min_instances != null ? var.worker_min_instances : local.env_config.worker_min_instances
      max_instance_count = var.worker_max_instances != null ? var.worker_max_instances : local.env_config.worker_max_instances
    }

    service_account = google_service_account.noetl_worker.email

    containers {
      image = local.worker_image

      resources {
        limits = {
          cpu    = var.worker_cpu_limit != "" ? var.worker_cpu_limit : local.env_config.worker_cpu_limit
          memory = var.worker_memory_limit != "" ? var.worker_memory_limit : local.env_config.worker_memory_limit
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }

      env {
        name  = "NOETL_RUN_MODE"
        value = "worker"
      }

      env {
        name  = "NOETL_WORKER_POOL_NAME"
        value = "worker-cpu-${count.index + 1}"
      }

      env {
        name  = "NOETL_WORKER_POOL_RUNTIME"
        value = "cpu"
      }

      env {
        name  = "LOG_LEVEL"
        value = var.log_level
      }

      env {
        name  = "POSTGRES_HOST"
        value = google_sql_database_instance.main.private_ip_address
      }

      env {
        name  = "POSTGRES_PORT"
        value = "5432"
      }

      env {
        name  = "POSTGRES_DB"
        value = var.db_name
      }

      env {
        name  = "POSTGRES_USER"
        value = var.db_user
      }

      env {
        name = "POSTGRES_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.db_password.secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "NOETL_SERVER_URL"
        value = google_cloud_run_v2_service.noetl_server.uri
      }

      env {
        name = "NOETL_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.noetl_api_key.secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }

      env {
        name  = "NOETL_DEBUG"
        value = var.enable_debug_mode ? "true" : "false"
      }

      # Health check configuration
      startup_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        initial_delay_seconds = 10
        timeout_seconds      = 5
        period_seconds       = 10
        failure_threshold    = 3
      }

      liveness_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        initial_delay_seconds = 30
        timeout_seconds      = 5
        period_seconds       = 30
        failure_threshold    = 3
      }
    }

    vpc_access {
      network_interfaces {
        network    = google_compute_network.vpc.name
        subnetwork = google_compute_subnetwork.subnet.name
        tags       = ["${local.name_prefix}-worker", "${local.name_prefix}-internal"]
      }
      egress = "ALL_TRAFFIC"
    }
  }

  traffic {
    percent = 100
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
  }

  depends_on = [google_cloud_run_v2_service.noetl_server]
}

# Cloud Run services for GPU workers (optional)
resource "google_cloud_run_v2_service" "noetl_worker_gpu" {
  count    = var.enable_gpu_workers ? var.gpu_worker_count : 0
  name     = "${local.name_prefix}-worker-gpu-${count.index + 1}"
  location = var.region
  
  labels = merge(local.common_labels, {
    worker_type = "gpu"
    worker_id   = tostring(count.index + 1)
  })

  template {
    labels = merge(local.common_labels, {
      worker_type = "gpu"
      worker_id   = tostring(count.index + 1)
    })
    
    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    service_account = google_service_account.noetl_worker.email

    containers {
      image = local.worker_image

      resources {
        limits = {
          cpu    = "4000m"
          memory = "8Gi"
        }
        cpu_idle          = false
        startup_cpu_boost = true
      }

      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }

      env {
        name  = "NOETL_RUN_MODE"
        value = "worker"
      }

      env {
        name  = "NOETL_WORKER_POOL_NAME"
        value = "worker-gpu-${count.index + 1}"
      }

      env {
        name  = "NOETL_WORKER_POOL_RUNTIME"
        value = "gpu"
      }

      env {
        name  = "LOG_LEVEL"
        value = var.log_level
      }

      env {
        name  = "POSTGRES_HOST"
        value = google_sql_database_instance.main.private_ip_address
      }

      env {
        name  = "POSTGRES_PORT"
        value = "5432"
      }

      env {
        name  = "POSTGRES_DB"
        value = var.db_name
      }

      env {
        name  = "POSTGRES_USER"
        value = var.db_user
      }

      env {
        name = "POSTGRES_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.db_password.secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "NOETL_SERVER_URL"
        value = google_cloud_run_v2_service.noetl_server.uri
      }

      env {
        name = "NOETL_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.noetl_api_key.secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }

      env {
        name  = "NOETL_DEBUG"
        value = var.enable_debug_mode ? "true" : "false"
      }
    }

    vpc_access {
      network_interfaces {
        network    = google_compute_network.vpc.name
        subnetwork = google_compute_subnetwork.subnet.name
        tags       = ["${local.name_prefix}-worker", "${local.name_prefix}-internal"]
      }
      egress = "ALL_TRAFFIC"
    }
  }

  traffic {
    percent = 100
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
  }

  depends_on = [google_cloud_run_v2_service.noetl_server]
}

# IAM policy for Cloud Run services to allow unauthenticated access
resource "google_cloud_run_service_iam_member" "noetl_server_public" {
  location = google_cloud_run_v2_service.noetl_server.location
  service  = google_cloud_run_v2_service.noetl_server.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Storage bucket for NoETL data
resource "google_storage_bucket" "noetl_data" {
  name          = "${var.project_id}-${local.name_prefix}-data"
  location      = var.region
  storage_class = "STANDARD"
  
  labels = local.common_labels

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }

  uniform_bucket_level_access = true
}
