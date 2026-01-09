---
sidebar_position: 6
title: Container Tool
description: Execute scripts in Kubernetes containers
---

# Container Tool

The Container tool executes shell scripts or commands in external Kubernetes containers (Jobs), enabling complex workloads with custom environments and dependencies.

## Basic Usage

```yaml
- step: run_script
  tool: container
  image: python:3.11-slim
  command: "python script.py"
  next:
    - step: process_results
```

## Configuration

### Required Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `image` | string | Container image to use |

### Optional Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `command` | string | - | Shell command to execute |
| `script` | string | - | Multi-line shell script |
| `args` | list | - | Arguments to pass to command |
| `env` | object | `{}` | Environment variables |
| `namespace` | string | `noetl` | Kubernetes namespace |
| `timeout` | int | 900 | Job timeout in seconds |
| `resources` | object | - | CPU/memory limits and requests |
| `service_account` | string | - | Kubernetes service account |
| `files` | list | - | Files to mount into container |

## Command Execution

### Simple Command

```yaml
- step: echo_test
  tool: container
  image: alpine:latest
  command: "echo 'Hello from container'"
```

### Multi-line Script

```yaml
- step: data_processing
  tool: container
  image: python:3.11-slim
  script: |
    #!/bin/bash
    pip install pandas numpy
    python -c "
    import pandas as pd
    import numpy as np
    data = np.random.rand(100, 3)
    df = pd.DataFrame(data, columns=['a', 'b', 'c'])
    print(df.describe())
    "
```

### With Arguments

```yaml
- step: run_with_args
  tool: container
  image: alpine:latest
  command: "echo"
  args:
    - "{{ workload.message }}"
    - "{{ vars.additional_text }}"
```

## Environment Variables

### Static Environment

```yaml
- step: with_env
  tool: container
  image: python:3.11
  env:
    DATABASE_URL: "postgresql://localhost:5432/mydb"
    LOG_LEVEL: "DEBUG"
    BATCH_SIZE: "1000"
  command: "python process.py"
```

### Template Variables

```yaml
- step: dynamic_env
  tool: container
  image: node:18
  env:
    API_ENDPOINT: "{{ workload.api_url }}"
    AUTH_TOKEN: "{{ keychain.api_token }}"
    EXECUTION_ID: "{{ execution_id }}"
  command: "node script.js"
```

## Resource Management

### CPU and Memory Limits

```yaml
- step: resource_intensive
  tool: container
  image: tensorflow/tensorflow:latest-gpu
  resources:
    limits:
      cpu: "4"
      memory: "8Gi"
    requests:
      cpu: "2"
      memory: "4Gi"
  script: |
    python train_model.py
```

### GPU Resources

```yaml
- step: gpu_workload
  tool: container
  image: nvidia/cuda:12.0-runtime
  resources:
    limits:
      nvidia.com/gpu: "1"
      memory: "16Gi"
  command: "python gpu_compute.py"
```

## File Mounting

### ConfigMap Files

Mount small files directly into the container:

```yaml
- step: with_config
  tool: container
  image: python:3.11
  files:
    - path: "config.yaml"
      content: |
        database:
          host: localhost
          port: 5432
        settings:
          batch_size: 1000
    - path: "script.py"
      content: |
        import yaml
        with open('/workspace/config.yaml') as f:
            config = yaml.safe_load(f)
        print(config)
  command: "python /workspace/script.py"
```

### Remote Files (GCS/S3/HTTP)

Load files from remote storage with authentication:

```yaml
- step: with_remote_files
  tool: container
  image: python:3.11
  files:
    - url: "gs://my-bucket/scripts/process.py"
      path: "process.py"
      auth: gcp_service_account
    - url: "https://api.example.com/config"
      path: "config.json"
      auth: api_bearer_token
  command: "python /workspace/process.py"
```

## Service Account

Run with specific Kubernetes service account:

```yaml
- step: privileged_task
  tool: container
  image: google/cloud-sdk:latest
  service_account: gcp-workload-identity
  command: "gcloud storage ls gs://my-bucket/"
```

## Timeout Configuration

```yaml
- step: long_running
  tool: container
  image: python:3.11
  timeout: 3600  # 1 hour
  script: |
    python long_running_job.py
```

## Response Format

```json
{
  "id": "task-uuid",
  "status": "success",
  "data": {
    "job_name": "noetl-container-abc123",
    "pod_name": "noetl-container-abc123-xyz",
    "exit_code": 0,
    "logs": "Container output...",
    "duration_seconds": 45.2
  }
}
```

## Examples

### Python Data Processing

```yaml
- step: process_data
  tool: container
  image: python:3.11-slim
  env:
    INPUT_PATH: "{{ workload.input_file }}"
    OUTPUT_PATH: "{{ workload.output_file }}"
  resources:
    limits:
      memory: "2Gi"
      cpu: "1"
  script: |
    #!/bin/bash
    pip install pandas pyarrow
    python << 'EOF'
    import pandas as pd
    import os
    
    input_path = os.environ['INPUT_PATH']
    output_path = os.environ['OUTPUT_PATH']
    
    df = pd.read_parquet(input_path)
    df['processed'] = True
    df.to_parquet(output_path)
    print(f"Processed {len(df)} rows")
    EOF
```

### Machine Learning Inference

```yaml
- step: ml_inference
  tool: container
  image: pytorch/pytorch:2.0.0-cuda11.7-runtime
  service_account: ml-inference-sa
  resources:
    limits:
      nvidia.com/gpu: "1"
      memory: "16Gi"
  env:
    MODEL_PATH: "gs://models/production/model.pt"
    INPUT_DATA: "{{ workload.input_uri }}"
  files:
    - url: "gs://ml-scripts/inference.py"
      path: "inference.py"
      auth: gcp_credentials
  command: "python /workspace/inference.py"
```

### Database Migration

```yaml
- step: run_migration
  tool: container
  image: flyway/flyway:latest
  env:
    FLYWAY_URL: "jdbc:postgresql://{{ keychain.db_host }}:5432/{{ keychain.db_name }}"
    FLYWAY_USER: "{{ keychain.db_user }}"
    FLYWAY_PASSWORD: "{{ keychain.db_password }}"
  files:
    - url: "gs://migrations/V001__initial.sql"
      path: "sql/V001__initial.sql"
      auth: gcp_service_account
  command: "flyway -locations=filesystem:/workspace/sql migrate"
```

### Node.js Build

```yaml
- step: build_frontend
  tool: container
  image: node:18-alpine
  resources:
    limits:
      memory: "4Gi"
      cpu: "2"
  script: |
    #!/bin/sh
    npm ci
    npm run build
    npm run test
    
    # Upload build artifacts
    tar -czf build.tar.gz dist/
    echo "Build complete"
```

### Multi-Container Workflow

```yaml
workflow:
  - step: start
    next:
      - step: prepare_data

  - step: prepare_data
    tool: container
    image: python:3.11
    script: |
      python prepare.py
    next:
      - step: train_model

  - step: train_model
    tool: container
    image: tensorflow/tensorflow:latest-gpu
    timeout: 7200
    resources:
      limits:
        nvidia.com/gpu: "1"
    script: |
      python train.py
    next:
      - step: evaluate

  - step: evaluate
    tool: container
    image: python:3.11
    script: |
      python evaluate.py
    next:
      - step: end

  - step: end
```

## Error Handling

Container failures are captured in the response:

```json
{
  "id": "task-uuid",
  "status": "error",
  "error": "Container exited with code 1",
  "data": {
    "exit_code": 1,
    "logs": "Error: File not found...",
    "job_name": "noetl-container-abc123"
  }
}
```

Handle errors with conditional routing:

```yaml
- step: risky_container
  tool: container
  image: python:3.11
  command: "python risky_script.py"
  next:
    - when: "{{ risky_container.status == 'error' }}"
      then:
        - step: handle_failure
    - step: continue_workflow
```

## Best Practices

1. **Use specific image tags**: Avoid `latest`, use versioned tags
2. **Set resource limits**: Prevent runaway containers
3. **Use read-only mounts**: Mount ConfigMaps as read-only when possible
4. **Clean up jobs**: Configure job TTL for automatic cleanup
5. **Use service accounts**: Apply least-privilege access
6. **Log effectively**: Ensure script output is captured for debugging

## Requirements

- Kubernetes cluster with Job support
- NoETL worker with Kubernetes client configured
- Appropriate RBAC permissions for creating Jobs

## See Also

- [Python Tool](/docs/reference/tools/python) - For inline Python execution
- [Script Attribute](/docs/features/script_attribute) - External script loading
- [Authentication Reference](/docs/reference/auth_and_keychain_reference)
