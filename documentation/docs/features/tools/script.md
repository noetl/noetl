# Script Tool

Execute scripts as Kubernetes Jobs with support for custom containers, dependencies, and resource management.

## Overview

The Script tool runs scripts in isolated Kubernetes Job pods, providing:
- Custom container images (Python, Node.js, etc.)
- Automatic dependency installation
- Resource limits and requests
- Environment variable injection via Secrets
- Script content via ConfigMaps
- Pod log capture

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   NoETL Worker  │────▶│  Kubernetes API │────▶│   Script Job    │
│                 │     │                 │     │   (Container)   │
│  Creates:       │     │  Manages:       │     │                 │
│  - ConfigMap    │     │  - Job lifecycle│     │  Runs script    │
│  - Secret       │     │  - Pod creation │     │  with args      │
│  - Job          │     │  - Log capture  │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## Configuration

### Basic Structure

```yaml
tool:
  kind: script
  script:
    type: inline
    content: |
      print("Hello from Kubernetes!")
  job:
    image: python:3.11-slim
    namespace: noetl
    timeout: 300
```

### Script Sources

| Type | Description |
|------|-------------|
| `inline` | Script content provided directly |
| `local` | Script content from local variable |
| `http` | Script fetched from HTTP URL |
| `gcs` | Script from Google Cloud Storage (requires auth) |
| `s3` | Script from AWS S3 (requires auth) |

## Examples

### Basic Python Script

```yaml
workflow:
  - step: run_analysis
    desc: Run Python analysis script
    tool:
      kind: script
      script:
        type: inline
        content: |
          import json
          import sys

          # Parse arguments
          args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}

          # Process data
          result = {
              "input": args,
              "processed": True,
              "count": len(args.get("items", []))
          }

          print(json.dumps(result))
      args:
        items: [1, 2, 3, 4, 5]
      job:
        image: python:3.11-slim
        timeout: 60
```

### With Dependencies

```yaml
workflow:
  - step: data_processing
    desc: Process data with pandas
    tool:
      kind: script
      script:
        type: inline
        content: |
          import pandas as pd
          import json
          import sys

          args = json.loads(sys.argv[1])

          # Create DataFrame
          df = pd.DataFrame(args.get("data", []))

          # Process
          result = {
              "rows": len(df),
              "columns": list(df.columns),
              "summary": df.describe().to_dict()
          }

          print(json.dumps(result))
      args:
        data:
          - name: "Alice"
            age: 30
          - name: "Bob"
            age: 25
      job:
        image: python:3.11-slim
        install_dependencies:
          - pandas
          - numpy
        timeout: 300
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "1Gi"
            cpu: "500m"
```

### With Environment Variables

```yaml
workflow:
  - step: api_integration
    desc: Call external API with credentials
    tool:
      kind: script
      script:
        type: inline
        content: |
          import os
          import requests
          import json

          api_key = os.environ.get("API_KEY")
          api_url = os.environ.get("API_URL")

          response = requests.get(
              f"{api_url}/data",
              headers={"Authorization": f"Bearer {api_key}"}
          )

          print(json.dumps(response.json()))
      job:
        image: python:3.11-slim
        install_dependencies:
          - requests
        env:
          API_KEY: "{{ secrets.EXTERNAL_API_KEY }}"
          API_URL: "https://api.example.com"
        timeout: 120
```

### From HTTP URL

```yaml
workflow:
  - step: run_remote_script
    desc: Execute script from URL
    tool:
      kind: script
      script:
        type: http
        uri: "https://raw.githubusercontent.com/org/repo/main/scripts/process.py"
      args:
        input_file: "/data/input.json"
        output_file: "/data/output.json"
      job:
        image: python:3.11-slim
        timeout: 600
```

### Custom Container Image

```yaml
workflow:
  - step: node_processing
    desc: Run Node.js script
    tool:
      kind: script
      script:
        type: inline
        content: |
          const args = JSON.parse(process.argv[2] || '{}');

          const result = {
            timestamp: new Date().toISOString(),
            input: args,
            processed: true
          };

          console.log(JSON.stringify(result));
      args:
        message: "Hello from Node.js"
      job:
        image: node:20-slim
        timeout: 60
```

### With Resource Limits

```yaml
workflow:
  - step: heavy_computation
    desc: Resource-intensive computation
    tool:
      kind: script
      script:
        type: inline
        content: |
          import numpy as np

          # Heavy computation
          data = np.random.randn(10000, 10000)
          result = np.linalg.svd(data, full_matrices=False)

          print(f"Computation complete: {result[1].shape}")
      job:
        image: python:3.11-slim
        install_dependencies:
          - numpy
        timeout: 1800
        backoff_limit: 1
        resources:
          requests:
            memory: "4Gi"
            cpu: "2"
          limits:
            memory: "8Gi"
            cpu: "4"
```

## Configuration Reference

### Script Configuration

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Script source type |
| `content` | string | No* | Inline script content |
| `uri` | string | No* | URL for remote scripts |

*Either `content` or `uri` is required depending on `type`.

### Job Configuration

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `image` | string | No | `python:3.11-slim` | Container image |
| `namespace` | string | No | `noetl` | Kubernetes namespace |
| `timeout` | integer | No | `600` | Job timeout in seconds |
| `backoff_limit` | integer | No | `3` | Number of retries |
| `ttl_seconds_after_finished` | integer | No | `300` | TTL for completed jobs |
| `install_dependencies` | array | No | `[]` | Python packages to install |
| `image_pull_policy` | string | No | `IfNotPresent` | Image pull policy |

### Resource Configuration

| Field | Type | Description |
|-------|------|-------------|
| `resources.requests.cpu` | string | CPU request (e.g., `100m`, `1`) |
| `resources.requests.memory` | string | Memory request (e.g., `128Mi`, `1Gi`) |
| `resources.limits.cpu` | string | CPU limit |
| `resources.limits.memory` | string | Memory limit |

### Environment Variables

| Field | Type | Description |
|-------|------|-------------|
| `env` | map | Key-value pairs for environment variables |

## Response Format

### Successful Execution

```json
{
  "status": "success",
  "data": {
    "status": "completed",
    "job_name": "noetl-script-abc123-xyz789",
    "namespace": "noetl",
    "pod_name": "noetl-script-abc123-xyz789-abcde",
    "execution_time": 45.23,
    "output": "{\"result\": \"success\", \"count\": 100}",
    "succeeded": 1,
    "failed": 0,
    "exit_code": 0
  },
  "duration_ms": 47532
}
```

### Failed Execution

```json
{
  "status": "error",
  "error": "Job failed with 1 failures",
  "data": {
    "status": "failed",
    "job_name": "noetl-script-abc123-xyz789",
    "namespace": "noetl",
    "pod_name": "noetl-script-abc123-xyz789-abcde",
    "execution_time": 12.5,
    "output": "Traceback (most recent call last):\n  File \"script.py\", line 5...",
    "succeeded": 0,
    "failed": 1,
    "exit_code": 1
  },
  "duration_ms": 15234
}
```

### Timeout

```json
{
  "status": "error",
  "error": "Job failed with 1 failures",
  "data": {
    "status": "timeout",
    "job_name": "noetl-script-abc123-xyz789",
    "namespace": "noetl",
    "execution_time": 600.0,
    "succeeded": 0,
    "failed": 1
  },
  "duration_ms": 600234
}
```

## Kubernetes Resources Created

For each script execution, the tool creates:

1. **ConfigMap**: Contains the script content
   - Name: `{job-name}-script`
   - Mounted at `/scripts/script.py`

2. **Secret** (if env vars provided): Contains environment variables
   - Name: `{job-name}-env`
   - Injected as environment variables

3. **Job**: Runs the script container
   - Name: `noetl-script-{execution-id}-{random}`
   - Auto-deleted after TTL

## Best Practices

1. **Set Appropriate Timeouts**:
   - Short scripts: 60-300 seconds
   - Data processing: 600-1800 seconds
   - Long-running: 3600+ seconds

2. **Use Resource Limits**:
   - Always set memory limits to prevent OOM
   - Set CPU limits for fair scheduling

3. **Handle Script Output**:
   - Print results as JSON for easy parsing
   - Use stdout for results, stderr for logs

4. **Secure Secrets**:
   - Use `env` with secrets for credentials
   - Never hardcode sensitive data in scripts

5. **Manage Dependencies**:
   - Pin dependency versions for reproducibility
   - Consider custom images for complex dependencies

## Limitations

- Script must output results to stdout
- Maximum script size limited by ConfigMap (1MB)
- GCS/S3 sources require additional authentication setup
- Pod logs may be truncated for very long outputs

## Troubleshooting

### Job Stuck in Pending

```bash
kubectl describe pod -n noetl <pod-name>
# Check for resource constraints or image pull issues
```

### Script Errors

```bash
# View job logs
kubectl logs -n noetl job/<job-name>

# Check events
kubectl get events -n noetl --sort-by='.lastTimestamp'
```

### Resource Issues

```bash
# Check resource quotas
kubectl describe resourcequota -n noetl

# Check node capacity
kubectl describe nodes
```

## See Also

- [Shell Tool](./shell) - Execute shell commands locally
- [Python Tool](./python) - Run Python scripts without Kubernetes
- [Rhai Tool](./rhai) - Lightweight scripting with Rhai
