# Outputs for NoETL services

output "server_url" {
  description = "URL of the NoETL server"
  value       = google_cloud_run_v2_service.noetl_server.uri
}

output "server_service_account_email" {
  description = "Email of the NoETL server service account"
  value       = google_service_account.noetl_server.email
}

output "worker_service_account_email" {
  description = "Email of the NoETL worker service account"
  value       = google_service_account.noetl_worker.email
}

output "cpu_worker_urls" {
  description = "URLs of the CPU worker services"
  value       = [for service in google_cloud_run_v2_service.noetl_worker_cpu : service.uri]
}

output "gpu_worker_urls" {
  description = "URLs of the GPU worker services"
  value       = var.enable_gpu_workers ? [for service in google_cloud_run_v2_service.noetl_worker_gpu : service.uri] : []
}

output "database_connection_name" {
  description = "Connection name for the Cloud SQL instance"
  value       = google_sql_database_instance.main.connection_name
}

output "database_private_ip" {
  description = "Private IP address of the Cloud SQL instance"
  value       = google_sql_database_instance.main.private_ip_address
}

output "vpc_network_name" {
  description = "Name of the VPC network"
  value       = google_compute_network.vpc.name
}

output "vpc_subnet_name" {
  description = "Name of the VPC subnet"
  value       = google_compute_subnetwork.subnet.name
}

output "storage_bucket_name" {
  description = "Name of the NoETL data storage bucket"
  value       = google_storage_bucket.noetl_data.name
}

output "secret_ids" {
  description = "Secret Manager secret IDs"
  value = {
    db_password  = google_secret_manager_secret.db_password.secret_id
    noetl_api_key = google_secret_manager_secret.noetl_api_key.secret_id
  }
}

output "project_id" {
  description = "Google Cloud project ID"
  value       = var.project_id
}

output "region" {
  description = "Google Cloud region"
  value       = var.region
}

output "environment" {
  description = "Environment name"
  value       = var.environment
}
