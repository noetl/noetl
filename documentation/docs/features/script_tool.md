---
sidebar_position: 14
title: Script Tool
---

# Script Tool - Kubernetes Job Execution

Execute scripts as isolated Kubernetes jobs with full resource management, credential injection, and monitoring. The script tool downloads scripts from cloud storage or HTTP endpoints and runs them as containerized jobs.

## Overview

The script tool enables:

- **Multi-cloud script sources** - Download from GCS, S3, HTTP, or local filesystem
- **Isolated execution** - Each script runs in its own Kubernetes job with dedicated resources
- **Credential injection** - Pass keychain tokens securely as environment variables
- **Resource limits** - Control CPU and memory allocation
- **Automatic retry** - Configurable failure handling with backoff
- **Auto-cleanup** - Jobs automatically deleted after completion
- **Full monitoring** - Capture logs, execution time, and status

## Basic Usage

### Minimal Configuration

```yaml
- step: run_analysis
  tool:
    kind: script
    script:
      uri: gs://my-bucket/scripts/analyze.py
      source:
        type: gcs
        auth: google_oauth
    args:
      dataset: sales_2024
    job:
      image: python:3.11-slim
```

### Full Configuration

```yaml
- step: data_processor
  tool:
    kind: script
    script:
      uri: gs://data-pipelines/scripts/processor.py
      source:
        type: gcs
        auth: gcp_service_account
    args:
      input_file: "{{ workload.input_path }}"
      output_bucket: "{{ workload.output_bucket }}"
      mode: batch
      chunk_size: 1000
    job:
      image: python:3.11-slim
      namespace: noetl
      ttlSecondsAfterFinished: 300
      backoffLimit: 3
      activeDeadlineSeconds: 3600
      resources:
        requests:
          memory: "512Mi"
          cpu: "1000m"
        limits:
          memory: "2Gi"
          cpu: "2000m"
      env:
        GCP_TOKEN: "{{ keychain.gcp_token.token }}"
        DATABASE_URL: "{{ secret.db_connection }}"
        LOG_LEVEL: "INFO"
```

## Script Sources

### Google Cloud Storage (GCS)

```yaml
script:
  uri: gs://bucket-name/path/to/script.py
  source:
    type: gcs
    auth: google_oauth  # Credential name registered in NoETL
```

**Requirements:**
- Credential with `storage.objects.get` permission
- Script must be accessible from cluster network
- URI must use `gs://` scheme

### AWS S3

```yaml
script:
  uri: s3://bucket-name/path/to/script.sql
  source:
    type: s3
    region: us-west-2
    auth: aws_credentials
```

**Requirements:**
- Credential with S3 read permissions
- Optional: specify AWS region
- URI must use `s3://` scheme

### HTTP/HTTPS

```yaml
script:
  uri: scripts/transform.py
  source:
    type: http
    endpoint: https://api.example.com
    method: GET
    headers:
      Authorization: "Bearer {{ secret.api_token }}"
    timeout: 30
```

**Requirements:**
- Script accessible via HTTP GET
- Optional authentication headers
- Can use full URL or relative path with endpoint

### Local Filesystem

```yaml
script:
  uri: ./scripts/local_script.py
  source:
    type: file
```

**Requirements:**
- Script exists in workspace filesystem
- Use relative or absolute paths
- No authentication required

## Credential Integration

### Keychain for Token Injection

Pass credentials from keychain to scripts via environment variables:

```yaml
keychain:
  - name: gcp_token
    kind: bearer
    scope: global
    credential: google_oauth

workflow:
  - step: process_data
    tool:
      kind: script
      script:
        uri: gs://bucket/scripts/processor.py
        source:
          type: gcs
          auth: google_oauth
      job:
        image: python:3.11-slim
        env:
          # Keychain tokens available in pod environment
          GCP_TOKEN: "{{ keychain.gcp_token.token }}"
          GCS_BUCKET: "{{ workload.bucket }}"
```

**How it works:**
1. NoETL creates Kubernetes Secret with environment variables
2. Pod mounts secret keys as environment variables
3. Script accesses via standard `os.environ.get('GCP_TOKEN')`
4. Secret automatically deleted when job completes

### Multiple Credentials

```yaml
job:
  env:
    GCP_TOKEN: "{{ keychain.gcp_token.token }}"
    AWS_ACCESS_KEY_ID: "{{ keychain.aws_cred.access_key }}"
    AWS_SECRET_ACCESS_KEY: "{{ keychain.aws_cred.secret_key }}"
    DATABASE_PASSWORD: "{{ secret.db_password }}"
```

## Job Configuration

### Resource Management

Control CPU and memory allocation:

```yaml
job:
  resources:
    requests:
      memory: "256Mi"    # Guaranteed allocation
      cpu: "500m"        # 0.5 CPU cores
    limits:
      memory: "1Gi"      # Maximum allowed
      cpu: "2000m"       # 2 CPU cores
```

**Best Practices:**
- Set requests based on typical usage
- Set limits higher to handle peak load
- Use Mi/Gi for memory, m for millicores
- Monitor actual usage to optimize

### Retry and Timeout

```yaml
job:
  backoffLimit: 3                 # Retry failed jobs up to 3 times
  activeDeadlineSeconds: 3600     # Kill job after 1 hour
  ttlSecondsAfterFinished: 300    # Delete job 5 minutes after completion
```

**Retry Behavior:**
- Job retries on non-zero exit code
- Exponential backoff between retries
- All attempts visible in job status

### Container Image

```yaml
job:
  image: python:3.11-slim         # Default: python:3.11-slim
  imagePullPolicy: IfNotPresent   # Default: IfNotPresent
```

**Supported Images:**
- Python: `python:3.11-slim`, `python:3.10`, etc.
- Custom: Build your own with required dependencies
- Private registries: Configure imagePullSecrets in namespace

### Namespace and Cleanup

```yaml
job:
  namespace: noetl                # Kubernetes namespace (default: noetl)
  ttlSecondsAfterFinished: 300    # Auto-cleanup after 5 minutes
```

## Script Arguments

Pass data to scripts via JSON arguments:

```yaml
args:
  input_file: "{{ workload.source }}"
  output_bucket: "{{ workload.destination }}"
  mode: incremental
  batch_size: 1000
  filters:
    status: active
    date_range:
      start: "2024-01-01"
      end: "2024-12-31"
```

**Script receives:**
```bash
# Arguments passed as JSON string in sys.argv[1]
$ python script.py '{"input_file": "data.csv", "output_bucket": "results", ...}'
```

## Execution Results

### Successful Execution

```json
{
  "status": "completed",
  "job_name": "script-process-data-522095307073519743",
  "pod_name": "script-process-data-522095307073519743-abcd1",
  "execution_time": 45.3,
  "output": "[INFO] Processing started...\n[INFO] Processed 1000 records\n[INFO] Complete",
  "succeeded": 1,
  "failed": 0
}
```

### Failed Execution

```json
{
  "status": "failed",
  "job_name": "script-process-data-522095307073519743",
  "pod_name": "script-process-data-522095307073519743-xyz99",
  "execution_time": 12.5,
  "output": "[ERROR] Connection timeout to database\n",
  "succeeded": 0,
  "failed": 3
}
```

## Use Cases

### Data Processing Pipeline

```yaml
- step: transform_data
  desc: Run Spark transformation on large dataset
  tool:
    kind: script
    script:
      uri: s3://data-pipelines/transformations/sales_aggregate.py
      source:
        type: s3
        region: us-east-1
        auth: aws_data_pipeline
    args:
      input_path: s3://raw-data/sales/2024/
      output_path: s3://processed-data/sales/aggregated/
      partition_by: month
    job:
      image: custom/spark-python:3.4
      resources:
        requests:
          memory: "4Gi"
          cpu: "2000m"
        limits:
          memory: "8Gi"
          cpu: "4000m"
```

### Database Migration

```yaml
- step: run_migration
  desc: Execute database schema migration
  tool:
    kind: script
    script:
      uri: gs://migrations/v2.5/upgrade_schema.sql
      source:
        type: gcs
        auth: gcp_service_account
    job:
      image: postgres:15-alpine
      resources:
        requests:
          memory: "256Mi"
          cpu: "500m"
      env:
        PGHOST: "{{ secret.db_host }}"
        PGUSER: "{{ secret.db_user }}"
        PGPASSWORD: "{{ secret.db_password }}"
        PGDATABASE: "{{ workload.database_name }}"
```

### Machine Learning Training

```yaml
- step: train_model
  desc: Train ML model with hyperparameter tuning
  tool:
    kind: script
    script:
      uri: gs://ml-pipelines/training/train_classifier.py
      source:
        type: gcs
        auth: google_oauth
    args:
      training_data: gs://datasets/training/features.parquet
      model_output: gs://models/classifier/v1.0
      hyperparameters:
        learning_rate: 0.001
        batch_size: 32
        epochs: 100
    job:
      image: tensorflow/tensorflow:2.14.0-gpu
      resources:
        requests:
          memory: "8Gi"
          cpu: "4000m"
          nvidia.com/gpu: 1
        limits:
          memory: "16Gi"
          cpu: "8000m"
          nvidia.com/gpu: 1
      env:
        GCP_TOKEN: "{{ keychain.gcp_token.token }}"
        WANDB_API_KEY: "{{ keychain.wandb_token.api_key }}"
```

### Batch ETL Job

```yaml
- step: extract_transform_load
  desc: Daily ETL batch processing
  tool:
    kind: script
    script:
      uri: https://github.com/company/etl-scripts/raw/main/daily_etl.py
      source:
        type: http
        timeout: 60
    args:
      date: "{{ workload.processing_date }}"
      sources:
        - name: crm
          connection: "{{ secret.crm_db }}"
        - name: analytics
          connection: "{{ secret.analytics_db }}"
      destination: "{{ secret.warehouse_db }}"
    job:
      image: python:3.11-slim
      activeDeadlineSeconds: 7200  # 2 hour timeout
      resources:
        requests:
          memory: "2Gi"
          cpu: "2000m"
```

## Monitoring and Debugging

### Check Job Status

```yaml
- step: verify_job
  desc: Check script execution result
  tool: python
  code: |
    def main(input_data):
        result = input_data.get('run_script_step', {})
        status = result.get('status')
        
        if status == 'completed':
            print(f"✓ Job succeeded in {result['execution_time']}s")
            return {"success": True}
        else:
            print(f"✗ Job failed: {result.get('output')}")
            raise Exception("Script execution failed")
  args:
    input_data: "{{ run_script_step }}"
```

### Logs and Output

The script tool captures all stdout/stderr from the pod:

```
[2024-12-21 10:30:15] Starting data processor
[2024-12-21 10:30:16] Connected to GCS bucket: data-pipelines
[2024-12-21 10:30:17] Processing file: sales_2024.csv
[2024-12-21 10:30:45] Processed 50,000 records
[2024-12-21 10:30:46] Uploaded results to: gs://results/processed/
[2024-12-21 10:30:46] Complete
```

### Kubernetes Integration

View jobs directly in Kubernetes:

```bash
# List NoETL script jobs
kubectl get jobs -n noetl -l app=noetl-script

# Check job status
kubectl describe job script-process-data-522095307073519743 -n noetl

# View pod logs
kubectl logs script-process-data-522095307073519743-abcd1 -n noetl
```

## Best Practices

### 1. Resource Sizing

- Start with conservative requests and increase based on monitoring
- Set limits 2-3x higher than requests for burst capacity
- Use memory limits to prevent OOM kills
- Profile scripts locally before Kubernetes deployment

### 2. Credential Management

- Always use keychain for cloud credentials
- Never hardcode tokens in scripts or playbooks
- Rotate credentials regularly via keychain auto-renewal
- Use least-privilege IAM roles for cloud storage access

### 3. Error Handling

- Set appropriate `backoffLimit` for transient failures
- Use `activeDeadlineSeconds` to prevent runaway jobs
- Implement idempotent scripts (safe to retry)
- Log progress frequently for debugging

### 4. Script Organization

- Store scripts in version-controlled repositories
- Use semantic versioning in GCS/S3 paths
- Test scripts locally before deploying to production
- Document script inputs, outputs, and dependencies

### 5. Performance Optimization

- Use slim container images to reduce startup time
- Cache dependencies in custom images
- Parallelize I/O operations in scripts
- Use batch processing for large datasets

### 6. Cleanup and TTL

- Set `ttlSecondsAfterFinished` to auto-cleanup completed jobs
- Use shorter TTL (60-300s) for frequent jobs
- Use longer TTL (3600s+) for debugging production issues
- Monitor cluster for orphaned jobs

## Limitations

- Scripts must be stateless (no shared filesystem between runs)
- Maximum job execution time controlled by `activeDeadlineSeconds`
- Pod resources limited by Kubernetes node capacity
- Large script files (>1MB) may slow job startup
- Secrets are base64-encoded (not encrypted at rest in ConfigMap)

## Troubleshooting

### Job Fails Immediately

**Symptom:** Job status shows `failed` with 0 execution time

**Possible causes:**
- Invalid container image
- Missing credentials for script download
- Syntax error in script
- Container lacks required dependencies

**Solution:** Check pod logs and job events

### Job Hangs/Timeout

**Symptom:** Job runs until `activeDeadlineSeconds` and is killed

**Possible causes:**
- Script waiting for input that never arrives
- Network connectivity issues
- Slow I/O operations
- Resource throttling (CPU/memory limits too low)

**Solution:** Add logging, increase timeout, check resource usage

### Out of Memory

**Symptom:** Pod killed with OOMKilled status

**Possible causes:**
- Memory limit too low for workload
- Memory leak in script
- Processing dataset larger than expected

**Solution:** Increase memory limit, optimize script, use streaming

### Credential Errors

**Symptom:** Script fails with authentication/authorization errors

**Possible causes:**
- Keychain token expired (should auto-refresh)
- Incorrect environment variable mapping
- Missing IAM permissions on cloud resources

**Solution:** Check keychain status, verify env vars, review IAM roles

## See Also

- [Keychain Token Refresh](./keychain_token_refresh) - Automatic credential renewal
- [Authentication & Keychain](/docs/reference/auth_and_keychain_reference) - Managing credentials
- [Container Tool](/docs/reference/tools/container) - Kubernetes container execution
- [Script Attribute](./script_attribute) - Loading scripts from external sources
