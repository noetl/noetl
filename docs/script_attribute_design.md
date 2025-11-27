# Script Attribute Design - External Script Execution

## Overview

This document defines the `script` attribute for NoETL playbooks, enabling standardized external script execution from various sources (GCS, S3, local files, HTTP). The design aligns with Azure Data Factory's linked service and dataset patterns for enterprise-grade data pipeline orchestration.

## Azure Data Factory Alignment

**ADF Pattern:**
- **LinkedService**: Connection definition (authentication, endpoint)
- **Dataset**: Data/file reference with format specification
- **Activity**: Execution with script reference

**NoETL Mapping:**
- **Credential**: Authentication (already exists in NoETL)
- **Script Attribute**: Combines dataset + activity script reference
- **Tool Plugin**: Activity execution engine

## Script Attribute Schema

### Structure

```yaml
script:
  path: string                    # Required: Path to script file
  source:                          # Required: Source configuration
    type: gcs|s3|file|http        # Required: Source type
    auth: string                   # Optional: Credential reference
    bucket: string                 # For gcs/s3: bucket name
    region: string                 # For s3: AWS region
    endpoint: string               # For http: full URL (overrides path)
    method: GET|POST               # For http: HTTP method (default: GET)
    headers: object                # For http: additional headers
    timeout: integer               # For http: timeout in seconds
  encoding: string                 # Optional: File encoding (default: utf-8)
  cache: boolean                   # Optional: Cache script locally (default: false)
```

### Priority Order

For plugins supporting both inline and external scripts:

1. **`script`** attribute (highest priority)
2. **`code_b64`** or **`command_b64`** (base64 encoded inline)
3. **`code`** or **`command`** (plain inline)

### Supported Plugins

| Plugin | Script Type | Current Inline | Priority |
|--------|-------------|----------------|----------|
| `python` | Python (.py) | `code`, `code_b64` | script > code_b64 > code |
| `postgres` | SQL (.sql) | `command`, `command_b64` | script > command_b64 > command |
| `duckdb` | SQL (.sql) | `query`, `query_b64` | script > query_b64 > query |
| `snowflake` | SQL (.sql) | `command`, `command_b64` | script > command_b64 > command |
| `http` | Template | `body`, `payload` | script > body > payload |

## Source Type Specifications

### 1. File Source (Local Filesystem)

```yaml
script:
  path: /path/to/script.py
  source:
    type: file
```

**Behavior:**
- Reads from local filesystem
- Supports absolute and relative paths (relative to playbook directory)
- No authentication required
- Fastest execution (no network overhead)

**Use Cases:**
- Development and testing
- Scripts in version control alongside playbooks
- Container-deployed scripts

### 2. GCS Source (Google Cloud Storage)

```yaml
script:
  path: scripts/transform.sql
  source:
    type: gcs
    bucket: my-data-pipelines
    auth: gcp_service_account
```

**Behavior:**
- Reads from GCS bucket using Google Cloud Storage client
- Requires credential with `storage.objects.get` permission
- Path is relative to bucket root
- Supports service account and HMAC authentication

**Authentication:**
- Credential type: `gcp_service_account` or `hmac`
- Resolved via NoETL credential system

**Use Cases:**
- Centralized script management
- Multi-environment deployments
- Team collaboration with version control in GCS

### 3. S3 Source (AWS S3)

```yaml
script:
  path: pipelines/load_data.py
  source:
    type: s3
    bucket: data-engineering-scripts
    region: us-east-1
    auth: aws_credentials
```

**Behavior:**
- Reads from AWS S3 using boto3
- Requires IAM credentials with `s3:GetObject` permission
- Path is relative to bucket root
- Region can be specified or auto-detected

**Authentication:**
- Credential type: `aws` with access_key_id and secret_access_key
- Supports IAM roles when running on EC2/ECS

**Use Cases:**
- AWS-native data pipelines
- Cross-account script sharing
- S3 versioning for script history

### 4. HTTP Source

```yaml
script:
  path: transform.sql  # Used as fallback if endpoint not specified
  source:
    type: http
    endpoint: https://api.example.com/scripts/transform.sql
    method: GET
    headers:
      Authorization: "Bearer {{ secret.api_token }}"
    timeout: 30
```

**Behavior:**
- Fetches script via HTTP/HTTPS request
- Supports custom headers for authentication
- Configurable timeout (default: 30 seconds)
- Endpoint can use Jinja2 templating

**Authentication:**
- No built-in credential resolution (use headers with Jinja2)
- Supports Bearer tokens, API keys in headers

**Use Cases:**
- Script management APIs
- GitLab/GitHub raw file URLs
- Internal script repositories with HTTP interfaces

## Implementation Architecture

### Module Structure

```
noetl/plugin/shared/script/
├── __init__.py           # Public API exports
├── resolver.py           # Main script resolution logic
├── sources/
│   ├── __init__.py
│   ├── gcs.py           # Google Cloud Storage handler
│   ├── s3.py            # AWS S3 handler
│   ├── file.py          # Local filesystem handler
│   └── http.py          # HTTP/HTTPS handler
├── auth.py              # Credential resolution
├── cache.py             # Optional script caching
└── validation.py        # Schema validation
```

### Core Functions

```python
# Main entry point
def resolve_script(
    script_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment
) -> str:
    """
    Resolve script from configured source.
    
    Returns:
        Script content as string
    
    Raises:
        ValueError: Invalid configuration
        ConnectionError: Source unavailable
        AuthenticationError: Credential resolution failed
    """
    pass

# Source-specific handlers
def fetch_from_gcs(path: str, bucket: str, credential: str) -> str:
    pass

def fetch_from_s3(path: str, bucket: str, region: str, credential: str) -> str:
    pass

def fetch_from_file(path: str, base_dir: str) -> str:
    pass

def fetch_from_http(endpoint: str, method: str, headers: Dict, timeout: int) -> str:
    pass
```

## Plugin Integration Pattern

### Python Plugin Example

```python
# noetl/plugin/tools/python/executor.py

async def _execute_python_task_async(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    args: Optional[Dict[str, Any]] = None,
    log_event_callback: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Execute a Python task asynchronously."""
    
    # Priority 1: Script attribute
    if 'script' in task_config:
        from noetl.plugin.shared.script import resolve_script
        code = resolve_script(task_config['script'], context, jinja_env)
        logger.debug(f"PYTHON: Resolved script from {task_config['script']['source']['type']}")
    
    # Priority 2: Base64 encoded code
    elif 'code_b64' in task_config:
        code = base64.b64decode(task_config['code_b64']).decode('utf-8')
        logger.debug("PYTHON: Using base64 encoded code")
    
    # Priority 3: Inline code
    elif 'code' in task_config:
        code = task_config['code']
        logger.debug("PYTHON: Using inline code")
    
    else:
        raise ValueError("No code provided: expected 'script', 'code_b64', or 'code'")
    
    # Rest of execution logic...
```

### Postgres Plugin Example

```python
# noetl/plugin/tools/postgres/command.py

def decode_base64_commands(task_config: Dict, context: Dict, jinja_env: Environment) -> str:
    """Decode SQL commands from task config with priority: script > command_b64 > command."""
    
    # Priority 1: Script attribute
    if 'script' in task_config:
        from noetl.plugin.shared.script import resolve_script
        sql = resolve_script(task_config['script'], context, jinja_env)
        logger.debug(f"POSTGRES: Resolved script from {task_config['script']['source']['type']}")
        return sql
    
    # Priority 2: Base64 encoded command
    if 'command_b64' in task_config:
        sql = base64.b64decode(task_config['command_b64']).decode('utf-8')
        return sql
    
    # Priority 3: Inline command
    if 'command' in task_config:
        return task_config['command']
    
    raise ValueError("No SQL command provided: expected 'script', 'command_b64', or 'command'")
```

## Playbook Examples

### Python with GCS Script

```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: python_gcs_script_example
  path: examples/script_execution/python_gcs

workload:
  gcs_bucket: data-pipelines-scripts
  gcp_cred: gcp_service_account

workflow:
  - step: start
    desc: Start workflow
    next:
      - step: run_python_from_gcs

  - step: run_python_from_gcs
    desc: Execute Python script from GCS
    tool: python
    script:
      path: analytics/transform_sales.py
      source:
        type: gcs
        bucket: "{{ workload.gcs_bucket }}"
        auth: "{{ workload.gcp_cred }}"
    args:
      input_table: sales_raw
      output_table: sales_transformed
    next:
      - step: end

  - step: end
    desc: End workflow
```

### Postgres with S3 Script

```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: postgres_s3_script_example
  path: examples/script_execution/postgres_s3

workload:
  s3_bucket: sql-scripts-prod
  aws_cred: aws_credentials
  pg_cred: pg_production

workflow:
  - step: start
    desc: Start workflow
    next:
      - step: run_migration_from_s3

  - step: run_migration_from_s3
    desc: Run database migration from S3
    tool: postgres
    auth: "{{ workload.pg_cred }}"
    script:
      path: migrations/v2.5/upgrade.sql
      source:
        type: s3
        bucket: "{{ workload.s3_bucket }}"
        region: us-west-2
        auth: "{{ workload.aws_cred }}"
    next:
      - step: end

  - step: end
    desc: End workflow
```

### DuckDB with Local File

```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: duckdb_file_script_example
  path: examples/script_execution/duckdb_file

workflow:
  - step: start
    desc: Start workflow
    next:
      - step: run_duckdb_from_file

  - step: run_duckdb_from_file
    desc: Execute DuckDB script from local file
    tool: duckdb
    script:
      path: ./scripts/aggregate_logs.sql
      source:
        type: file
    next:
      - step: end

  - step: end
    desc: End workflow
```

### HTTP Script Fetch

```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: python_http_script_example
  path: examples/script_execution/python_http

workload:
  script_api: https://scripts.example.com/api/v1

workflow:
  - step: start
    desc: Start workflow
    next:
      - step: fetch_script_from_api

  - step: fetch_script_from_api
    desc: Fetch and execute Python script from HTTP API
    tool: python
    script:
      path: data_quality_check.py  # Fallback if endpoint not specified
      source:
        type: http
        endpoint: "{{ workload.script_api }}/scripts/data_quality_check.py"
        method: GET
        headers:
          Authorization: "Bearer {{ secret.api_token }}"
        timeout: 30
    args:
      dataset: customers
    next:
      - step: end

  - step: end
    desc: End workflow
```

## Error Handling

### Validation Errors

```python
# Invalid configuration
{
  "error": "script.source.type is required",
  "status": "error"
}

# Missing required fields
{
  "error": "script.path is required for gcs source",
  "status": "error"
}
```

### Source Errors

```python
# File not found
{
  "error": "Script file not found: /path/to/script.py",
  "status": "error"
}

# GCS/S3 object not found
{
  "error": "Object not found: gs://bucket/path/script.sql",
  "status": "error"
}

# HTTP fetch failed
{
  "error": "HTTP 404: Script not found at https://api.example.com/script.py",
  "status": "error"
}
```

### Authentication Errors

```python
# Credential not found
{
  "error": "Credential 'gcp_service_account' not found",
  "status": "error"
}

# Permission denied
{
  "error": "Permission denied: storage.objects.get on gs://bucket/script.py",
  "status": "error"
}
```

## Backward Compatibility

All existing playbooks using inline `code`, `code_b64`, `command`, `command_b64` will continue to work without changes. The `script` attribute is additive and takes priority when present.

### Migration Path

1. **Phase 1**: Implement script resolution in plugins (backward compatible)
2. **Phase 2**: Document script attribute in DSL spec
3. **Phase 3**: Create test fixtures demonstrating usage
4. **Phase 4**: Optional: Add warnings for large inline scripts suggesting external storage

## Performance Considerations

### Caching

```yaml
script:
  path: scripts/expensive_transform.py
  source:
    type: s3
    bucket: scripts
  cache: true  # Cache script locally for execution duration
```

- Cache scripts for the duration of execution to avoid repeated fetches
- Cache invalidation based on playbook execution ID
- Optional persistent cache with TTL for frequently used scripts

### Network Optimization

- Parallel script fetching for multi-step playbooks
- Connection pooling for cloud storage clients
- HTTP keep-alive for multiple HTTP script fetches

## Testing Strategy

### Unit Tests

- `tests/plugin/shared/test_script_resolver.py`: Core resolution logic
- `tests/plugin/shared/test_script_sources.py`: Source-specific handlers
- Mock GCS/S3 clients to avoid external dependencies

### Integration Tests

- `tests/fixtures/playbooks/script_execution/`: Complete playbook examples
- Test each source type (file, gcs, s3, http)
- Test each plugin (python, postgres, duckdb, snowflake)
- Test error scenarios (missing files, auth failures, network errors)

### Task-Based Testing

```bash
task test-script-file-full       # File source integration test
task test-script-gcs-full        # GCS source integration test
task test-script-s3-full         # S3 source integration test
task test-script-http-full       # HTTP source integration test
```

## Security Considerations

1. **Path Traversal Protection**: Validate paths to prevent `../../etc/passwd` attacks
2. **Credential Isolation**: Scripts cannot access credential store directly
3. **Network Policies**: HTTP source respects firewall and network policies
4. **Code Injection**: Script content treated as data until execution in sandbox
5. **Audit Logging**: Log script source, path, and fetch events for compliance

## Documentation Updates

### Files to Update

1. `docs/dsl_spec.md`: Add script attribute to all relevant step types
2. `.github/copilot-instructions.md`: Document script pattern with examples
3. `docs/plugin_architecture_refactoring.md`: Add script resolution to shared services
4. `docs/examples.md`: Link to script execution examples

### Example Structure

```markdown
## Script Attribute (External Code Execution)

All action tools (python, postgres, duckdb, snowflake, http) support the `script` attribute for loading code from external sources:

- **GCS**: `script.source.type: gcs`
- **S3**: `script.source.type: s3`
- **File**: `script.source.type: file`
- **HTTP**: `script.source.type: http`

See `tests/fixtures/playbooks/script_execution/` for complete examples.
```

## Implementation Checklist

- [ ] Create `noetl/plugin/shared/script/` package structure
- [ ] Implement `resolver.py` with main resolution logic
- [ ] Implement source handlers: `file.py`, `gcs.py`, `s3.py`, `http.py`
- [ ] Implement credential resolution in `auth.py`
- [ ] Implement validation in `validation.py`
- [ ] Update Python plugin: `noetl/plugin/tools/python/executor.py`
- [ ] Update Postgres plugin: `noetl/plugin/tools/postgres/command.py`
- [ ] Update DuckDB plugin: `noetl/plugin/tools/duckdb/executor.py`
- [ ] Update Snowflake plugin: `noetl/plugin/tools/snowflake/command.py`
- [ ] Update HTTP plugin: `noetl/plugin/tools/http/executor.py`
- [ ] Create test fixtures in `tests/fixtures/playbooks/script_execution/`
- [ ] Update `docs/dsl_spec.md`
- [ ] Update `.github/copilot-instructions.md`
- [ ] Add unit tests for script resolution
- [ ] Add integration tests with task definitions
- [ ] Update `pyproject.toml` dependencies (boto3 for S3, google-cloud-storage for GCS)

## Future Enhancements

1. **Script Versioning**: Support version pinning for GCS/S3 scripts
2. **Script Registry**: Centralized script catalog with metadata
3. **Script Templating**: Jinja2 templating within scripts themselves
4. **Script Validation**: Pre-execution linting for SQL/Python scripts
5. **Script Analytics**: Track script usage, performance, and errors
