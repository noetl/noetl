# Script Execution Examples

This directory contains test playbooks demonstrating the `script` attribute for external code execution from various sources.

## Structure

```
script_execution/
├── scripts/                       # Sample scripts for testing
│   ├── hello_world.py            # Python script (file source)
│   ├── create_test_table.sql     # SQL script (file source)
│   └── data_processor.py         # Python script for K8s job execution
├── python_file_example.yaml      # Python with file source
├── postgres_file_example.yaml    # Postgres with file source
├── python_http_example.yaml      # Python with HTTP source
├── python_gcs_example.yaml       # Python with GCS source
├── postgres_s3_example.yaml      # Postgres with S3 source
├── k8s_job_python_gcs.yaml       # Kubernetes Job execution from GCS
└── README.md                     # This file
```

## Script Attribute Pattern

All action tools (python, postgres, duckdb, snowflake, http) support the `script` attribute:

```yaml
script:
  uri: gs://bucket-name/path/to/script.py  # Required: Full URI with scheme
  source:                                   # Required: Source configuration
    type: file|gcs|s3|http                 # Required: Source type
    # Source-specific fields:
    region: aws-region                      # For s3 (optional)
    auth: credential-reference              # For gcs/s3 authentication
    endpoint: https://url                   # For http (base URL)
    method: GET                             # For http (default: GET)
    headers: {}                             # For http
    timeout: 30                             # For http (seconds)
```

**URI Formats:**
- GCS: `gs://bucket-name/path/to/script.py` (required format)
- S3: `s3://bucket-name/path/to/script.sql` (required format)
- FILE: `./scripts/script.py` or `/absolute/path/script.py`
- HTTP: Relative path with `source.endpoint` or full URL

## Priority Order

When multiple code sources are present in a step, NoETL uses only one based on this priority:

1. **`script`** - External script (highest priority) - **If present, all other sources are ignored**
2. **`code_b64`** or **`command_b64`** - Base64 encoded inline - **Used only if `script` is not present**
3. **`code`** or **`command`** - Plain inline - **Used only if neither `script` nor `code_b64` exist**

**Example:**
```yaml
- step: transform
  tool: python
  code: |
    def main():
        return "This will be IGNORED"
  code_b64: "VGhpcyB3aWxsIGFsc28gYmUgSUdOT1JFRA=="
  script:
    uri: gs://bucket/scripts/transform.py  # This will be executed
    source:
      type: gcs
      auth: google_oauth
```

In the example above, NoETL will execute the GCS script and completely ignore both `code` and `code_b64` fields.

## Examples

### 1. File Source (Local Filesystem)

**Python:**
```yaml
- step: run_script
  tool: python
  script:
    uri: ./scripts/hello_world.py
    source:
      type: file
  args:
    name: NoETL
```

**Postgres:**
```yaml
- step: run_migration
  tool: postgres
  auth: pg_local
  script:
    uri: ./scripts/create_test_table.sql
    source:
      type: file
```

### 2. HTTP Source

```yaml
- step: fetch_and_run
  tool: python
  script:
    uri: script.py
    source:
      type: http
      endpoint: https://api.example.com/scripts/transform.py
      method: GET
      headers:
        Authorization: "Bearer {{ secret.api_token }}"
      timeout: 30
  args:
    input_data: data
```

### 3. GCS Source (Requires GCP Credentials)

```yaml
- step: run_from_gcs
  tool: python
  script:
    uri: gs://data-pipelines-scripts/analytics/transform.py
    source:
      type: gcs
      auth: gcp_service_account
  args:
    dataset: sales
```

### 4. S3 Source (Requires AWS Credentials)

```yaml
- step: run_migration_from_s3
  tool: postgres
  auth: pg_production
  script:
    uri: s3://sql-scripts-prod/migrations/v2.5/upgrade.sql
    source:
      type: s3
      region: us-west-2
      auth: aws_credentials
```

### 5. Kubernetes Job Execution (New in v2)

Execute scripts as Kubernetes jobs with resource limits, retries, and monitoring:

```yaml
keychain:
  - name: gcp_token
    kind: bearer
    scope: global
    credential: google_oauth

workflow:
  - step: run_script_as_k8s_job
    desc: Execute Python script from GCS as Kubernetes job
    tool:
      kind: script
      script:
        uri: gs://noetl-demo-19700101/scripts/data_processor.py
        source:
          type: gcs
          auth: google_oauth
      args:
        input_file: sample_dataset.csv
        output_bucket: noetl-results
        mode: batch
      job:
        image: python:3.11-slim
        namespace: noetl
        ttlSecondsAfterFinished: 300
        backoffLimit: 3
        resources:
          requests:
            memory: "256Mi"
            cpu: "500m"
          limits:
            memory: "512Mi"
            cpu: "1000m"
        env:
          # Credentials from keychain available as environment variables in pod
          GCP_TOKEN: "{{ keychain.gcp_token.token }}"
          GCS_BUCKET: "{{ workload.output_bucket }}"
```

**Features:**
- Downloads script from GCS, S3, HTTP, or local filesystem
- Creates Kubernetes Job with script mounted as ConfigMap
- Configurable resource limits (CPU, memory)
- Automatic retry on failure (backoffLimit)
- Auto-cleanup after completion (ttlSecondsAfterFinished)
- Returns job status, pod logs, and execution time
- Supports timeout configuration
- **Credential injection via keychain**: Pass credentials as environment variables to pod

**Job Result:**
```yaml
{
  "status": "completed",
  "job_name": "script-run-script-as-k8s-job-522095307073519743",
  "pod_name": "script-run-script-as-k8s-job-522095307073519743-abcd1",
  "execution_time": 45.3,
  "output": "[DATA PROCESSOR] Starting in batch mode\n[DATA PROCESSOR] Processed 1000 records\n...",
  "succeeded": 1,
  "failed": 0
}
```

**Example Script Structure:**
```python
#!/usr/bin/env python3
import sys
import json
import os

def main():
    # Parse arguments from command line (passed as JSON string)
    if len(sys.argv) > 1:
        args = json.loads(sys.argv[1])
    else:
        args = {}

    input_file = args.get('input_file', 'unknown')
    output_bucket = args.get('output_bucket', 'unknown')

    # Access environment variables (including credentials from keychain)
    gcp_token = os.environ.get('GCP_TOKEN', 'not_set')
    gcs_bucket = os.environ.get('GCS_BUCKET', 'not_set')

    print(f"[DATA PROCESSOR] Processing {input_file}")
    print(f"[DATA PROCESSOR] GCP Token available: {gcp_token != 'not_set'}")

    # Your processing logic here (can use credentials for cloud storage access)

    # Output result as JSON for NoETL to capture
    result = {
        "status": "completed",
        "records_processed": 1000,
        "output_location": f"gs://{output_bucket}/results/output.csv",
        "environment": {
            "gcp_token_available": gcp_token != 'not_set',
            "gcs_bucket": gcs_bucket
        }
    }

    print(json.dumps(result))
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

## Testing

### Prerequisites

**File Source:**
- No special setup required
- Scripts in `scripts/` directory

**HTTP Source:**
- Internet connectivity
- Optional: GitHub repository with test scripts

**GCS Source:**
- Google Cloud project
- Service account with `storage.objects.get` permission
- Scripts uploaded to GCS bucket
- Credential registered in NoETL: `noetl credential create gcp_service_account --type gcp ...`
- **Credential Integration**: Complete - automatically fetches from NoETL API

**S3 Source:**
- AWS account
- IAM credentials with `s3:GetObject` permission
- Scripts uploaded to S3 bucket
- Credential registered in NoETL: `noetl credential create aws_credentials --type aws ...`
- **Credential Integration**: Complete - automatically fetches from NoETL API

### Running Tests

```bash
# File source tests (no cloud credentials required)
noetl playbook register tests/fixtures/playbooks/script_execution/python_file_example.yaml
noetl execution create python_file_script_example --data '{}'

noetl playbook register tests/fixtures/playbooks/script_execution/postgres_file_example.yaml
noetl execution create postgres_file_script_example --data '{}'

# HTTP source test (requires internet)
noetl playbook register tests/fixtures/playbooks/script_execution/python_http_example.yaml
noetl execution create python_http_script_example --data '{}'

# Cloud source tests (requires credentials - see Prerequisites above)
noetl playbook register tests/fixtures/playbooks/script_execution/python_gcs_example.yaml
noetl execution create python_gcs_script_example --data '{}'

noetl playbook register tests/fixtures/playbooks/script_execution/postgres_s3_example.yaml
noetl execution create postgres_s3_script_example --data '{}'

# Kubernetes Job execution test (requires GCS credentials)
# First, upload test script to GCS:
gsutil cp scripts/data_processor.py gs://noetl-demo-19700101/scripts/

# Then register and execute
noetl playbook register tests/fixtures/playbooks/script_execution/k8s_job_python_gcs.yaml
noetl execution create k8s_job_python_gcs --data '{}'
```

## Backward Compatibility

All existing playbooks using inline `code`, `code_b64`, `command`, or `command_b64` continue to work without changes. The `script` attribute is additive.

### Migration Example

**Before (inline code):**
```yaml
- step: transform
  tool: python
  code: |
    def main(data):
        return {"transformed": data}
```

**After (external script):**
```yaml
- step: transform
  tool: python
  script:
    uri: ./scripts/transform.py
    source:
      type: file
```

## Security Considerations

1. **Path Traversal**: File paths are validated to prevent `../../` attacks
2. **Credentials**: Cloud sources use NoETL credential system
3. **HTTP SSL**: HTTPS endpoints verified by default
4. **Timeouts**: HTTP requests have configurable timeouts
5. **Audit**: All script fetches logged with source and path

## See Also

- `docs/script_attribute_design.md` - Complete design specification
- `docs/dsl_spec.md` - Full DSL documentation
- `.github/copilot-instructions.md` - Development guide
