# DuckDB GCS Workload Identity Test Playbook

This playbook demonstrates DuckDB integration with Google Cloud Storage using workload identity authentication in Kubernetes.

## Overview

The playbook showcases:
- Creating sample data in DuckDB
- Uploading Parquet files to GCS using workload identity
- Downloading files from GCS with different names
- Performing aggregations on GCS-stored data
- Multiple read/write operations to verify authentication

## Workload Identity Authentication

This playbook is designed to run in a GKE cluster with workload identity enabled. The key features:

### Automatic Authentication
- No explicit credentials (HMAC keys or service account JSON) required
- DuckDB automatically fetches OAuth tokens from GCP metadata service (169.254.169.254)
- Uses `SET gcs_access_mode = 'auto';` for automatic token management

### Requirements
1. **GKE Cluster** with workload identity enabled
2. **Kubernetes Service Account** linked to GCP service account
3. **GCP Service Account** with Storage Object Admin permissions on the target bucket
4. **Workload Identity Binding** between K8s SA and GCP SA

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ NoETL Worker Pod (Kubernetes)                               │
│                                                              │
│  ┌─────────────┐                                            │
│  │   DuckDB    │                                            │
│  │   Engine    │                                            │
│  └──────┬──────┘                                            │
│         │                                                    │
│         │ 1. Request GCS access                             │
│         ▼                                                    │
│  ┌─────────────────────────────────────┐                   │
│  │  GCP Metadata Service Client        │                   │
│  │  (169.254.169.254)                  │                   │
│  └──────┬──────────────────────────────┘                   │
└─────────┼──────────────────────────────────────────────────┘
          │
          │ 2. Fetch OAuth token
          ▼
┌─────────────────────────────────────────────────────────────┐
│ GCP Metadata Service                                        │
│ (Workload Identity Provider)                               │
│                                                              │
│  - Validates K8s Service Account                           │
│  - Returns short-lived OAuth token                         │
│  - Maps to GCP Service Account identity                    │
└──────┬──────────────────────────────────────────────────────┘
       │
       │ 3. Use token for GCS operations
       ▼
┌─────────────────────────────────────────────────────────────┐
│ Google Cloud Storage                                        │
│                                                              │
│  gs://noetl-demo-19700101/weather/                         │
│    ├── weather_data_<execution_id>.parquet                 │
│    ├── weather_data_downloaded_<execution_id>.parquet      │
│    └── aggregation_<execution_id>.parquet                  │
└─────────────────────────────────────────────────────────────┘
```

## Workflow Steps

### 1. Create Sample Data
Creates 100 rows of synthetic weather data with:
- Execution ID tracking
- 5 European cities (London, Paris, Berlin, Madrid, Rome)
- Random temperature and humidity values
- Timestamp for each measurement

### 2. Upload to GCS
- Writes data as Parquet format with ZSTD compression
- Uses workload identity for authentication (automatic)
- Stores at: `gs://noetl-demo-19700101/weather/weather_data_<execution_id>.parquet`

### 3. Download with New Name
- Reads the uploaded file from GCS
- Verifies data integrity
- Writes to new location: `weather_data_downloaded_<execution_id>.parquet`
- Confirms both files exist

### 4. Aggregate Results
- Reads downloaded file from GCS
- Creates city-level aggregations (avg, min, max for temperature and humidity)
- Writes aggregation results to GCS
- Final verification of all created files

## Configuration

### Workload Variables
```yaml
workload:
  gcs_bucket: noetl-demo-19700101          # Target GCS bucket
  source_file: weather_data_{{ execution_id }}.parquet
  downloaded_file: weather_data_downloaded_{{ execution_id }}.parquet
```

### DuckDB GCS Settings
```sql
-- Automatic workload identity mode (recommended)
SET gcs_access_mode = 'auto';

-- Alternative explicit settings (not needed with auto mode)
-- SET gcs_endpoint = 'storage.googleapis.com';
-- SET gcs_use_ssl = true;
```

## Testing

### Prerequisites
```bash
# Verify GKE cluster has workload identity enabled
kubectl get nodes -o jsonpath='{.items[0].metadata.annotations.workload\.googleapis\.com/cluster-name}'

# Check service account binding
kubectl get serviceaccount noetl-worker -o yaml | grep workload

# Verify GCP service account has permissions
gcloud projects get-iam-policy noetl-demo-19700101 \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:noetl-worker@noetl-demo-19700101.iam.gserviceaccount.com"
```

### Register and Execute
```bash
# Register playbook to catalog
task register-playbook -- tests/fixtures/playbooks/duckdb_gcs_workload_identity/duckdb_gcs_workload_identity.yaml

# Execute playbook
task execute-playbook -- tests/fixtures/playbooks/duckdb_gcs_workload_identity/workload_identity

# Monitor execution
task logs-worker
```

### Verification
```bash
# Check created files in GCS
gsutil ls gs://noetl-demo-19700101/weather/

# Download and inspect a file
gsutil cp gs://noetl-demo-19700101/weather/weather_data_*.parquet /tmp/
duckdb -c "SELECT * FROM '/tmp/weather_data_*.parquet' LIMIT 10;"
```

## Troubleshooting

### Authentication Failures
If you see authentication errors:

1. **Check workload identity binding**:
   ```bash
   gcloud iam service-accounts get-iam-policy \
     noetl-worker@noetl-demo-19700101.iam.gserviceaccount.com
   ```

2. **Verify metadata service access**:
   ```bash
   kubectl exec -it <worker-pod> -- curl -H "Metadata-Flavor: Google" \
     http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token
   ```

3. **Check GCS permissions**:
   ```bash
   gcloud projects get-iam-policy noetl-demo-19700101 \
     --flatten="bindings[].members" \
     --filter="bindings.role:roles/storage"
   ```

### DuckDB Extension Issues
```sql
-- Verify httpfs extension is available
SELECT * FROM duckdb_extensions() WHERE extension_name = 'httpfs';

-- Check GCS configuration
SELECT name, value FROM duckdb_settings() WHERE name LIKE 'gcs%';
```

## Security Considerations

### Advantages of Workload Identity
- ✅ No credential files to manage or rotate
- ✅ Short-lived OAuth tokens (automatically refreshed)
- ✅ Identity tied to Kubernetes service account
- ✅ Centralized permission management in IAM
- ✅ Audit trail via GCP Cloud Logging

### Best Practices
- Use separate GCP service accounts for different workloads
- Grant minimum required permissions (Principle of Least Privilege)
- Monitor service account usage via Cloud Audit Logs
- Regularly review and rotate workload identity bindings

## Related Documentation
- [Google Cloud Workload Identity](https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity)
- [DuckDB httpfs Extension](https://duckdb.org/docs/extensions/httpfs)
- [NoETL Google Cloud Service Account Guide](../../../../docs/google_cloud_service_account.md)
