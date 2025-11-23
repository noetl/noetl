# Script Attribute Implementation Summary

## Overview

Implemented standardized external script execution for NoETL playbooks, aligning with Azure Data Factory's linked service pattern. Scripts can now be loaded from GCS, S3, local files, or HTTP endpoints.

## Implementation Status

### ✅ Completed

1. **Design Documentation** (`docs/script_attribute_design.md`)
   - Complete specification with ADF alignment
   - Source type definitions (file, gcs, s3, http)
   - Priority order: script > code_b64 > code
   - Security considerations and error handling
   - Examples for all source types

2. **Script Resolution Module** (`noetl/plugin/shared/script/`)
   - `resolver.py`: Main coordination logic
   - `validation.py`: Configuration validation
   - `sources/file.py`: Local filesystem handler
   - `sources/gcs.py`: Google Cloud Storage handler
   - `sources/s3.py`: AWS S3 handler
   - `sources/http.py`: HTTP/HTTPS handler

3. **Plugin Updates**
   - **Python**: `noetl/plugin/tools/python/executor.py`
     - Priority: script > code_b64 > code
     - Full backward compatibility
   - **Postgres**: `noetl/plugin/tools/postgres/command.py` + `executor.py`
     - Priority: script > command_b64 > command
     - Integrated with existing command parsing

4. **Test Fixtures** (`tests/fixtures/playbooks/script_execution/`)
   - Sample scripts: `hello_world.py`, `create_test_table.sql`
   - Python file example: `python_file_example.yaml`
   - Postgres file example: `postgres_file_example.yaml`
   - Python HTTP example: `python_http_example.yaml`
   - README with usage instructions

5. **Documentation Updates**
   - `.github/copilot-instructions.md`: Added script attribute section with examples
   - Design doc includes migration path and testing strategy

### 🔄 In Progress / Future Work

6. **DuckDB Plugin** - Not yet implemented
7. **Snowflake Plugin** - Not yet implemented
8. **HTTP Plugin** - Not yet implemented (lower priority)
9. **DSL Spec** - `docs/dsl_spec.md` needs script attribute documentation
10. **Credential Integration** - GCS/S3 handlers have placeholder for NoETL credential resolution

## Architecture

### Script Resolution Flow

```
Playbook Step
    ↓
Plugin Executor (priority check)
    ↓
resolve_script(config, context, jinja_env)
    ↓
validate_script_config(config)
    ↓
Source Handler (file|gcs|s3|http)
    ↓
Script Content (string)
    ↓
Plugin Execution (existing logic)
```

### Module Structure

```
noetl/plugin/shared/script/
├── __init__.py           # Public API
├── resolver.py           # Main logic
├── validation.py         # Config validation
└── sources/
    ├── __init__.py
    ├── file.py          # Local filesystem ✅
    ├── gcs.py           # Google Cloud Storage ✅
    ├── s3.py            # AWS S3 ✅
    └── http.py          # HTTP/HTTPS ✅
```

## Usage Examples

### 1. Python with Local File

```yaml
- step: transform
  tool: python
  script:
    path: ./scripts/transform.py
    source:
      type: file
  args:
    data: input
```

### 2. Postgres with GCS

```yaml
- step: migration
  tool: postgres
  auth: pg_prod
  script:
    path: migrations/v2.5/upgrade.sql
    source:
      type: gcs
      bucket: sql-scripts
      auth: gcp_service_account
```

### 3. Python with HTTP

```yaml
- step: fetch_script
  tool: python
  script:
    path: script.py
    source:
      type: http
      endpoint: https://api.example.com/scripts/transform.py
      headers:
        Authorization: "Bearer {{ secret.api_token }}"
      timeout: 30
```

### 4. Postgres with S3

```yaml
- step: load_data
  tool: postgres
  auth: pg_prod
  script:
    path: sql/load_customers.sql
    source:
      type: s3
      bucket: data-pipelines
      region: us-west-2
      auth: aws_credentials
```

## Testing

### Test Files Created

1. `tests/fixtures/playbooks/script_execution/scripts/hello_world.py`
   - Function-based Python script
   - Demonstrates argument passing and return values

2. `tests/fixtures/playbooks/script_execution/scripts/create_test_table.sql`
   - Multi-statement SQL script
   - Table creation and data insertion

3. `tests/fixtures/playbooks/script_execution/python_file_example.yaml`
   - Complete playbook with verification step
   - Tests file source with Python plugin

4. `tests/fixtures/playbooks/script_execution/postgres_file_example.yaml`
   - SQL script execution with cleanup
   - Tests file source with Postgres plugin

5. `tests/fixtures/playbooks/script_execution/python_http_example.yaml`
   - HTTP script fetching
   - Uses GitHub raw URL as example

### Running Tests

```bash
# File source (no cloud credentials required)
task playbook:k8s:register tests/fixtures/playbooks/script_execution/python_file_example.yaml
task playbook:k8s:execute python_file_script_example

task playbook:k8s:register tests/fixtures/playbooks/script_execution/postgres_file_example.yaml
task playbook:k8s:execute postgres_file_script_example

# HTTP source (requires internet)
task playbook:k8s:register tests/fixtures/playbooks/script_execution/python_http_example.yaml
task playbook:k8s:execute python_http_script_example
```

## Key Features

### 1. Priority Order
Plugins check in order: `script` > `code_b64`/`command_b64` > `code`/`command`

### 2. Backward Compatibility
All existing playbooks continue to work without changes.

### 3. Source Types
- **file**: Local filesystem (fastest, for development/testing)
- **gcs**: Google Cloud Storage (centralized management)
- **s3**: AWS S3 (AWS-native pipelines)
- **http**: HTTP/HTTPS endpoints (script APIs, GitHub raw URLs)

### 4. Authentication
- File source: No authentication required
- GCS/S3: Credential references via NoETL credential system
- HTTP: Custom headers with Jinja2 templating

### 5. Security
- Path traversal prevention (validates `..`)
- SSL verification for HTTPS (default enabled)
- Configurable timeouts for HTTP
- Credential isolation (scripts can't access credential store)

### 6. Jinja2 Integration
- Script paths can use templates: `{{ workload.script_path }}`
- HTTP endpoints support templating
- HTTP headers support templating for auth tokens

## ADF Alignment

### Azure Data Factory Pattern

```
LinkedService (connection) → Dataset (file reference) → Activity (execution)
```

### NoETL Pattern

```
Credential (auth) → Script Attribute (source config) → Tool Plugin (execution)
```

### Mapping

| ADF Concept | NoETL Equivalent | Description |
|-------------|------------------|-------------|
| LinkedService | Credential | Authentication configuration |
| Dataset | script.source | File/object reference |
| Activity | Tool Plugin | Execution engine |
| Integration Runtime | Worker | Execution environment |

## Dependencies

### Required Python Packages

```toml
# pyproject.toml additions needed:
google-cloud-storage = "^2.10.0"  # For GCS source
boto3 = "^1.28.0"                  # For S3 source
requests = "^2.31.0"               # For HTTP source (already present)
```

### Installation

```bash
pip install google-cloud-storage boto3
# or
uv pip install google-cloud-storage boto3
```

## Next Steps

### Immediate (Required for Full Functionality)

1. **Credential Integration**: Implement GCS/S3 credential resolution
   - Update `sources/gcs.py`: Replace `TODO` with actual credential lookup
   - Update `sources/s3.py`: Replace `TODO` with actual credential lookup
   - Connect to `noetl.plugin.shared.auth` credential system

2. **DuckDB Plugin**: Add script support
   - Similar pattern to Postgres
   - Update query parsing logic

3. **Snowflake Plugin**: Add script support
   - Similar pattern to Postgres
   - Update command parsing logic

4. **DSL Spec**: Update `docs/dsl_spec.md`
   - Document script attribute for each tool type
   - Add source type specifications
   - Include complete examples

### Future Enhancements

5. **Script Caching**: Implement local caching
   - Cache scripts for execution duration
   - Optional persistent cache with TTL

6. **Script Validation**: Pre-execution validation
   - SQL syntax checking (using sqlparse)
   - Python syntax checking (using ast.parse)

7. **Script Versioning**: Support version pinning
   - GCS object versioning
   - S3 object versioning
   - Git commit SHAs for GitHub URLs

8. **Script Registry**: Centralized script catalog
   - Metadata tracking (author, version, description)
   - Usage analytics
   - Dependency management

9. **Script Templating**: Jinja2 within scripts
   - Render scripts before execution
   - Pass context variables to scripts

## Breaking Changes

None. This is a purely additive feature. All existing playbooks continue to work without modification.

## Migration Path

### Phase 1 (Current): Core Implementation
- ✅ Script resolution module
- ✅ Python and Postgres plugins
- ✅ File and HTTP sources working
- ✅ GCS and S3 sources implemented (pending credential integration)

### Phase 2 (Next): Complete Coverage
- Update remaining plugins (DuckDB, Snowflake)
- Integrate credential resolution
- Update DSL specification
- Add comprehensive tests

### Phase 3 (Future): Advanced Features
- Script caching
- Script validation
- Script versioning
- Script registry

## Files Changed

### Created
1. `docs/script_attribute_design.md` (670 lines)
2. `noetl/plugin/shared/script/__init__.py`
3. `noetl/plugin/shared/script/resolver.py`
4. `noetl/plugin/shared/script/validation.py`
5. `noetl/plugin/shared/script/sources/__init__.py`
6. `noetl/plugin/shared/script/sources/file.py`
7. `noetl/plugin/shared/script/sources/gcs.py`
8. `noetl/plugin/shared/script/sources/s3.py`
9. `noetl/plugin/shared/script/sources/http.py`
10. `tests/fixtures/playbooks/script_execution/` (directory)
11. `tests/fixtures/playbooks/script_execution/scripts/hello_world.py`
12. `tests/fixtures/playbooks/script_execution/scripts/create_test_table.sql`
13. `tests/fixtures/playbooks/script_execution/python_file_example.yaml`
14. `tests/fixtures/playbooks/script_execution/postgres_file_example.yaml`
15. `tests/fixtures/playbooks/script_execution/python_http_example.yaml`
16. `tests/fixtures/playbooks/script_execution/README.md`

### Modified
1. `noetl/plugin/tools/python/executor.py`
   - Added script resolution (lines 207-212)
   - Updated error message (line 229)

2. `noetl/plugin/tools/postgres/command.py`
   - Updated `decode_base64_commands()` signature
   - Added script resolution (lines 50-60)
   - Updated error message (line 87)

3. `noetl/plugin/tools/postgres/executor.py`
   - Updated function call (line 163)

4. `.github/copilot-instructions.md`
   - Added "Script Attribute" section
   - Added examples and priority order
   - Added reference to test fixtures

### Total Changes
- **16 new files**
- **4 modified files**
- **~1,500 lines of new code**
- **~50 lines modified**

## Documentation

### Complete Documentation Available
1. `docs/script_attribute_design.md` - Full specification
2. `tests/fixtures/playbooks/script_execution/README.md` - Usage guide
3. `.github/copilot-instructions.md` - Developer guide section

### Documentation Pending
1. `docs/dsl_spec.md` - Needs script attribute section

## Known Limitations

1. **Credential Resolution**: GCS/S3 handlers need integration with NoETL credential system
2. **Plugin Coverage**: DuckDB, Snowflake, HTTP plugins not yet updated
3. **Caching**: No script caching implemented yet
4. **Validation**: No pre-execution script validation
5. **Testing**: Cloud source tests require manual setup (credentials, buckets)

## Success Metrics

### Achieved
- ✅ ADF-aligned architecture
- ✅ Zero breaking changes
- ✅ Complete file source implementation
- ✅ Complete HTTP source implementation
- ✅ Test fixtures with working examples
- ✅ Comprehensive design documentation

### To Measure
- Script execution performance vs inline code
- Adoption rate once fully deployed
- Script reuse across playbooks
- Cloud storage cost impact

## Conclusion

The script attribute implementation provides NoETL with enterprise-grade external script management aligned with Azure Data Factory patterns. The feature is backward compatible, well-documented, and includes working examples for immediate use. Remaining work focuses on completing plugin coverage and integrating credential resolution for cloud sources.
