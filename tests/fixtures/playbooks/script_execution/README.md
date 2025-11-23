# Script Execution Examples

This directory contains test playbooks demonstrating the `script` attribute for external code execution from various sources.

## Structure

```
script_execution/
├── scripts/                       # Sample scripts for testing
│   ├── hello_world.py            # Python script (file source)
│   └── create_test_table.sql     # SQL script (file source)
├── python_file_example.yaml      # Python with file source
├── postgres_file_example.yaml    # Postgres with file source
├── python_http_example.yaml      # Python with HTTP source
├── python_gcs_example.yaml       # Python with GCS source ✅ credential integration
├── postgres_s3_example.yaml      # Postgres with S3 source ✅ credential integration
└── README.md                     # This file
```

## Script Attribute Pattern

All action tools (python, postgres, duckdb, snowflake, http) support the `script` attribute:

```yaml
script:
  path: path/to/script.py          # Required: Script path/key
  source:                           # Required: Source configuration
    type: file|gcs|s3|http         # Required: Source type
    # Source-specific fields:
    bucket: bucket-name             # For gcs/s3
    region: aws-region              # For s3
    auth: credential-reference      # For gcs/s3
    endpoint: https://url           # For http
    method: GET                     # For http (default: GET)
    headers: {}                     # For http
    timeout: 30                     # For http (seconds)
```

## Priority Order

When multiple code sources are present:

1. **`script`** - External script (highest priority)
2. **`code_b64`** or **`command_b64`** - Base64 encoded inline
3. **`code`** or **`command`** - Plain inline

## Examples

### 1. File Source (Local Filesystem)

**Python:**
```yaml
- step: run_script
  tool: python
  script:
    path: ./scripts/hello_world.py
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
    path: ./scripts/create_test_table.sql
    source:
      type: file
```

### 2. HTTP Source

```yaml
- step: fetch_and_run
  tool: python
  script:
    path: script.py
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
    path: analytics/transform.py
    source:
      type: gcs
      bucket: data-pipelines-scripts
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
    path: migrations/v2.5/upgrade.sql
    source:
      type: s3
      bucket: sql-scripts-prod
      region: us-west-2
      auth: aws_credentials
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
- Credential registered in NoETL: `task playbook:k8s:register-credential-gcp`
- **Credential Integration**: ✅ Complete - automatically fetches from NoETL API

**S3 Source:**
- AWS account
- IAM credentials with `s3:GetObject` permission
- Scripts uploaded to S3 bucket
- Credential registered in NoETL: `task playbook:k8s:register-credential-aws`
- **Credential Integration**: ✅ Complete - automatically fetches from NoETL API

### Running Tests

```bash
# File source tests (no cloud credentials required)
task playbook:k8s:register tests/fixtures/playbooks/script_execution/python_file_example.yaml
task playbook:k8s:execute python_file_script_example

task playbook:k8s:register tests/fixtures/playbooks/script_execution/postgres_file_example.yaml
task playbook:k8s:execute postgres_file_script_example

# HTTP source test (requires internet)
task playbook:k8s:register tests/fixtures/playbooks/script_execution/python_http_example.yaml
task playbook:k8s:execute python_http_script_example

# Cloud source tests (requires credentials - see Prerequisites above)
task playbook:k8s:register tests/fixtures/playbooks/script_execution/python_gcs_example.yaml
task playbook:k8s:execute python_gcs_script_example

task playbook:k8s:register tests/fixtures/playbooks/script_execution/postgres_s3_example.yaml
task playbook:k8s:execute postgres_s3_script_example
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
    path: ./scripts/transform.py
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
