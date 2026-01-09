# Python Tool

## Overview

The `python` tool executes Python code within NoETL workflows, supporting both inline code and external scripts from cloud storage. It provides flexible parameter passing, authentication injection, and seamless integration with workflow context.

## Key Features

- **Inline Code Execution**: Write Python directly in playbook YAML
- **External Script Loading**: Load code from GCS, S3, HTTP, or local files
- **Authentication Injection**: Automatic environment variable setup for cloud SDKs
- **Flexible Parameter Resolution**: Multiple ways to pass arguments to Python functions
- **Context Integration**: Access workflow variables, execution state, and previous step results
- **Async Support**: Execute Python functions synchronously or asynchronously

## Basic Usage

### Inline Python Code

```yaml
- step: transform_data
  tool: python
  code: |
    def main(input_data):
        """Transform input data."""
        result = [x * 2 for x in input_data]
        return {"transformed": result, "count": len(result)}
  args:
    input_data: [1, 2, 3, 4, 5]
```

**Output:**
```json
{
  "transformed": [2, 4, 6, 8, 10],
  "count": 5
}
```

### External Script (GCS)

```yaml
- step: run_analysis
  tool: python
  script:
    uri: gs://my-bucket/scripts/analyze.py
    source:
      type: gcs
      auth: google_service_account
  args:
    dataset: sales_2024
    threshold: 1000
```

### External Script (S3)

```yaml
- step: process_data
  tool: python
  script:
    uri: s3://data-pipelines/scripts/processor.py
    source:
      type: s3
      region: us-west-2
      auth: aws_credentials
  args:
    input_file: "{{ workload.input_path }}"
    output_bucket: "{{ workload.output_bucket }}"
```

### External Script (HTTP)

```yaml
- step: fetch_and_run
  tool: python
  script:
    uri: transform.py
    source:
      type: http
      endpoint: https://api.example.com/scripts
      headers:
        Authorization: "Bearer {{ secret.api_token }}"
      timeout: 30
  args:
    data: "{{ previous_step.result }}"
```

### External Script (Local File)

```yaml
- step: local_transform
  tool: python
  script:
    uri: ./scripts/transform.py
    source:
      type: file
  args:
    input: "{{ workload.data }}"
```

## Configuration

### Required Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `code` | string | One of* | Inline Python code (function named `main`) |
| `code_b64` | string | One of* | Base64-encoded Python code |
| `script` | object | One of* | External script configuration |

**\*Priority Order:** `script` > `code_b64` > `code` (if multiple specified, highest priority wins)

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `args` | dict | {} | Arguments passed to Python function |
| `auth` | string/dict | null | Authentication for cloud SDK access |
| `name` | string | unnamed_python_task | Task name for logging |

### Script Configuration

When using external scripts, configure with `script` attribute:

```yaml
script:
  uri: gs://bucket/path/to/script.py  # Full URI with scheme
  source:
    type: gcs|s3|http|file           # Source type
    auth: credential_name             # Authentication (GCS/S3)
    region: aws-region                # AWS region (S3 only)
    endpoint: https://api.url         # Base URL (HTTP only)
    method: GET                       # HTTP method (default: GET)
    headers: {}                       # HTTP headers (HTTP only)
    timeout: 30                       # HTTP timeout seconds (HTTP only)
```

**URI Formats:**
- GCS: `gs://bucket-name/path/to/script.py` (required format)
- S3: `s3://bucket-name/path/to/script.sql` (required format)
- File: `./scripts/transform.py` or `/abs/path/script.py`
- HTTP: Relative path with `source.endpoint` or full URL

## Python Function Patterns

### Basic Function

Python code must define a `main` function as the entry point:

```yaml
- step: calculate
  tool: python
  code: |
    def main(x, y):
        return x + y
  args:
    x: 10
    y: 20
```

### Function with Defaults

Support optional parameters with default values:

```yaml
- step: greet
  tool: python
  code: |
    def main(name, greeting="Hello"):
        return f"{greeting}, {name}!"
  args:
    name: "World"
    # greeting uses default "Hello"
```

### Function with Context

Access full execution context via special `context` parameter:

```yaml
- step: context_aware
  tool: python
  code: |
    def main(data, context):
        """Access execution metadata."""
        execution_id = context.get('execution_id')
        catalog_id = context.get('catalog_id')
        step_name = context.get('step')
        
        return {
            "data": data,
            "execution_id": execution_id,
            "step": step_name
        }
  args:
    data: [1, 2, 3]
```

### Function with **kwargs

Accept arbitrary keyword arguments:

```yaml
- step: flexible
  tool: python
  code: |
    def main(**kwargs):
        """Process all workflow variables."""
        return {
            "received_keys": list(kwargs.keys()),
            "total_args": len(kwargs)
        }
  args:
    field1: "value1"
    field2: "value2"
    field3: "value3"
```

### Async Function

Use async/await for I/O operations:

```yaml
- step: async_task
  tool: python
  code: |
    import asyncio
    
    async def main(delay, message):
        """Async function with sleep."""
        await asyncio.sleep(delay)
        return {"message": message, "delay": delay}
  args:
    delay: 0.5
    message: "Task completed"
```

## Authentication Integration

### Automatic Credential Injection

The Python tool automatically injects cloud credentials as environment variables:

```yaml
- step: upload_to_gcs
  tool: python
  auth: google_service_account  # Injects GOOGLE_APPLICATION_CREDENTIALS
  code: |
    from google.cloud import storage
    
    def main(bucket_name, file_path):
        # Credentials auto-discovered from environment
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob("output/data.csv")
        blob.upload_from_filename(file_path)
        return {"uploaded": True, "bucket": bucket_name}
  args:
    bucket_name: my-data-bucket
    file_path: /tmp/output.csv
```

### Supported Services

| Service | Environment Variables Set | Use Case |
|---------|--------------------------|----------|
| `gcs` | `GOOGLE_APPLICATION_CREDENTIALS` | Google Cloud Storage access |
| `gcs_service_account` | `GOOGLE_APPLICATION_CREDENTIALS` | Service account JSON key |
| `gcs_hmac` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | GCS S3-compatible API |
| `s3`, `aws` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` | AWS S3 access |
| `azure` | `AZURE_STORAGE_CONNECTION_STRING` | Azure Blob Storage |

### Multiple Credentials

Use `credentials` block for multiple authentication contexts:

```yaml
- step: multi_cloud
  tool: python
  credentials:
    gcs_cred:
      key: google_service_account
    aws_cred:
      key: aws_credentials
  code: |
    from google.cloud import storage as gcs_storage
    import boto3
    
    def main(gcs_bucket, s3_bucket):
        # GCS client uses GOOGLE_APPLICATION_CREDENTIALS
        gcs_client = gcs_storage.Client()
        gcs_bucket_obj = gcs_client.bucket(gcs_bucket)
        
        # S3 client uses AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
        s3_client = boto3.client('s3')
        
        return {"gcs": gcs_bucket, "s3": s3_bucket}
  args:
    gcs_bucket: my-gcs-bucket
    s3_bucket: my-s3-bucket
```

## Parameter Resolution

### Resolution Order

Arguments are resolved from multiple sources in this priority:

1. **Explicit `args`**: Values in the `args` field
2. **Context Input**: `context.input` from previous step results
3. **Context Data**: `context.data` from execution state
4. **Context Root**: Other values in execution context

```yaml
# Step 1: Returns data
- step: fetch_data
  tool: postgres
  query: "SELECT * FROM users LIMIT 5"

# Step 2: Receives result from fetch_data
- step: process
  tool: python
  code: |
    def main(user_data):
        """user_data automatically populated from fetch_data result."""
        return {"count": len(user_data)}
  args:
    user_data: "{{ fetch_data }}"  # Explicit reference to previous step
```

### Parameter Coercion

String values are automatically parsed to Python objects when possible:

```yaml
- step: parse_json
  tool: python
  code: |
    def main(json_obj, json_array):
        """Strings automatically parsed to dict/list."""
        return {
            "obj_type": type(json_obj).__name__,   # 'dict'
            "array_type": type(json_array).__name__ # 'list'
        }
  args:
    json_obj: '{"key": "value"}'     # Parsed to dict
    json_array: '[1, 2, 3]'          # Parsed to list
```

## Advanced Patterns

### Data Transformation Pipeline

```yaml
- step: transform_pipeline
  tool: python
  code: |
    def main(data, operations):
        """Apply transformation pipeline."""
        result = data
        for op in operations:
            if op == "double":
                result = [x * 2 for x in result]
            elif op == "filter_even":
                result = [x for x in result if x % 2 == 0]
            elif op == "sum":
                result = sum(result)
        return {"result": result, "operations": operations}
  args:
    data: [1, 2, 3, 4, 5]
    operations: ["double", "filter_even", "sum"]
```

**Output:**
```json
{
  "result": 20,
  "operations": ["double", "filter_even", "sum"]
}
```

### Error Handling

```yaml
- step: safe_division
  tool: python
  code: |
    def main(numerator, denominator):
        """Division with error handling."""
        try:
            result = numerator / denominator
            return {"result": result, "success": True}
        except ZeroDivisionError:
            return {"error": "Division by zero", "success": False}
        except Exception as e:
            return {"error": str(e), "success": False}
  args:
    numerator: 10
    denominator: 0
```

### External Library Usage

```yaml
- step: analyze_data
  tool: python
  code: |
    import pandas as pd
    import numpy as np
    
    def main(csv_path):
        """Analyze CSV data with pandas."""
        df = pd.read_csv(csv_path)
        
        return {
            "rows": len(df),
            "columns": list(df.columns),
            "mean_values": df.select_dtypes(include=[np.number]).mean().to_dict(),
            "missing_values": df.isnull().sum().to_dict()
        }
  args:
    csv_path: "/data/sales.csv"
```

**Note**: Ensure required libraries are installed in worker environment.

### Complex Return Values

```yaml
- step: generate_report
  tool: python
  code: |
    from datetime import datetime
    
    def main(user_id, transactions):
        """Generate user transaction report."""
        total = sum(t['amount'] for t in transactions)
        avg = total / len(transactions) if transactions else 0
        
        return {
            "user_id": user_id,
            "report_date": datetime.now().isoformat(),
            "summary": {
                "total_transactions": len(transactions),
                "total_amount": total,
                "average_amount": avg,
                "categories": list(set(t['category'] for t in transactions))
            },
            "transactions": transactions
        }
  args:
    user_id: "{{ workload.user_id }}"
    transactions: "{{ fetch_transactions }}"
```

## Script Execution Examples

### GCS Script with Service Account

```yaml
workload:
  gcs_bucket: analytics-scripts
  script_path: scripts/monthly_report.py
  report_month: "2024-01"

workflow:
  - step: start
    next:
      - step: generate_report

  - step: generate_report
    tool: python
    script:
      uri: "gs://{{ workload.gcs_bucket }}/{{ workload.script_path }}"
      source:
        type: gcs
        auth: gcp_service_account
    args:
      month: "{{ workload.report_month }}"
      output_format: json
    next:
      - step: save_report

  - step: save_report
    tool: postgres
    auth: analytics_db
    query: |
      INSERT INTO reports (month, data, created_at)
      VALUES ($1, $2, NOW())
    parameters:
      - "{{ workload.report_month }}"
      - "{{ generate_report | tojson }}"
    next:
      - step: end

  - step: end
```

### S3 Script with Multiple Parameters

```yaml
- step: etl_process
  tool: python
  script:
    uri: s3://etl-scripts/pipelines/daily_etl.py
    source:
      type: s3
      region: us-west-2
      auth: aws_admin_role
  args:
    execution_date: "{{ workload.execution_date }}"
    source_tables:
      - orders
      - customers
      - products
    target_schema: warehouse
    mode: incremental
    chunk_size: 10000
```

### HTTP Script with Authentication

```yaml
- step: run_shared_logic
  tool: python
  script:
    uri: common/validators.py
    source:
      type: http
      endpoint: https://scripts.company.com
      method: GET
      headers:
        Authorization: "Bearer {{ secret.script_api_token }}"
        X-Api-Version: "v1"
      timeout: 60
  args:
    data: "{{ workload.input_data }}"
    validation_rules:
      - required_fields
      - data_types
      - business_logic
```

### Local Script with Development Override

```yaml
- step: local_development
  tool: python
  script:
    uri: "{{ workload.script_path | default('./scripts/dev_processor.py') }}"
    source:
      type: file
  args:
    debug: true
    verbose_logging: true
    data: "{{ workload.test_data }}"
```

## Best Practices

### 1. Function Naming

Always name your entry function `main`:

```python
# ✅ Correct
def main(x, y):
    return x + y

# ❌ Wrong
def process(x, y):
    return x + y
```

### 2. Type Hints

Use type hints for clarity:

```python
from typing import Dict, List, Any

def main(user_ids: List[int], config: Dict[str, Any]) -> Dict[str, int]:
    """Process user data with type hints."""
    return {"processed": len(user_ids)}
```

### 3. Error Messages

Provide descriptive error messages:

```python
def main(value):
    if value < 0:
        raise ValueError(f"Expected positive value, got {value}")
    return {"result": value * 2}
```

### 4. Logging

Use print statements for logging (captured by NoETL):

```python
def main(data):
    print(f"Processing {len(data)} records")
    result = process_data(data)
    print(f"Completed: {len(result)} results")
    return result
```

### 5. Return Values

Return JSON-serializable objects:

```python
from datetime import datetime

def main(record_id):
    # ✅ Convert datetime to string
    return {
        "id": record_id,
        "processed_at": datetime.now().isoformat()
    }
    
    # ❌ Don't return datetime objects directly
    # return {"processed_at": datetime.now()}
```

### 6. Script Organization

Structure external scripts with clear entry points:

```python
# scripts/data_processor.py

import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

def validate_input(data: List[Dict]) -> bool:
    """Validate input data structure."""
    return all(isinstance(item, dict) for item in data)

def transform_record(record: Dict) -> Dict:
    """Transform single record."""
    return {
        "id": record.get("id"),
        "value": record.get("value", 0) * 2
    }

def main(data: List[Dict], mode: str = "full") -> Dict[str, Any]:
    """Main entry point called by NoETL."""
    logger.info(f"Processing {len(data)} records in {mode} mode")
    
    if not validate_input(data):
        raise ValueError("Invalid input data structure")
    
    results = [transform_record(record) for record in data]
    
    return {
        "processed": len(results),
        "mode": mode,
        "results": results
    }
```

### 7. Authentication Patterns

Use cloud SDK auto-discovery:

```python
# ✅ Let SDK discover credentials from environment
from google.cloud import storage

def main(bucket_name):
    client = storage.Client()  # Auto-discovers GOOGLE_APPLICATION_CREDENTIALS
    bucket = client.bucket(bucket_name)
    return {"bucket": bucket_name}

# ❌ Avoid hardcoding credentials
def main(bucket_name, credentials_json):
    # Don't pass credentials as parameters
    pass
```

## Limitations

1. **No *args Support**: Variadic positional arguments not allowed
2. **Synchronous Execution**: Python code runs synchronously (unless using async/await)
3. **Memory Limits**: Subject to worker memory constraints
4. **Timeout**: Long-running operations may timeout (configure worker timeout)
5. **Library Availability**: Only libraries installed in worker environment are available
6. **Context Size**: Large context data may impact performance

## Troubleshooting

### Missing Required Argument

**Error**: `TypeError: Missing required argument 'x' for Python task`

**Solution**: Ensure all function parameters are provided via `args` or context:

```yaml
- step: fix_missing_arg
  tool: python
  code: |
    def main(x, y):  # Both x and y are required
        return x + y
  args:
    x: 10
    y: 20  # Don't forget this!
```

### Import Error

**Error**: `ModuleNotFoundError: No module named 'pandas'`

**Solution**: Ensure library is installed in worker environment or use standard library:

```yaml
# Option 1: Use standard library
- step: use_stdlib
  tool: python
  code: |
    import json
    import csv
    
    def main(data):
        return json.dumps(data)

# Option 2: Request library installation in worker image
```

### Script Loading Failed

**Error**: `Failed to load script from GCS gs://bucket/script.py`

**Solution**: Verify:
- URI format is correct (`gs://` prefix)
- Credential has read permissions
- Script exists at specified path
- Network connectivity from worker to cloud storage

### Authentication Not Working

**Error**: `google.auth.exceptions.DefaultCredentialsError`

**Solution**: Ensure `auth` field references valid credential:

```yaml
- step: fix_auth
  tool: python
  auth: google_service_account  # Must be registered credential
  code: |
    from google.cloud import storage
    def main():
        client = storage.Client()
        return {"authenticated": True}
```

## See Also

- [Script Tool](/docs/features/script_tool) - Kubernetes job execution
- [HTTP Tool](./http) - REST API integration
- [PostgreSQL Tool](./postgres) - Database operations
- [Script Attribute](/docs/features/script_attribute) - GCS/S3/HTTP script loading
