# NoETL Development Guide for AI Coding Agents

NoETL is a workflow automation framework for data processing and MLOps orchestration with a distributed server-worker architecture.

## Documentation Standards

**CRITICAL**: All documentation must go in `documentation/docs/` (Docusaurus format), NOT in `docs/` folder at project root.

## Repo Hygiene (No Root Scripts/Docs)

**CRITICAL**: Do not add new scripts, one-off utilities, or documentation files to the repository root.

- **Scripts**: put under `scripts/` (project utilities) or `tests/scripts/` (test helpers)
- **Documentation**: put under `documentation/docs/` only
- **Test fixtures**: put under `tests/fixtures/`
- **Tooling**: put under `tools/` when appropriate

- **Location**: `documentation/docs/` for all new documentation
- **Format**: Markdown with Docusaurus frontmatter (sidebar_position, etc.)
- **Configuration**: `documentation/docusaurus.config.ts`
- **Categories**: Use `documentation/docs/reference/`, `documentation/docs/features/`, etc.
- **Never Create**: `docs/` folder at project root - it has been removed

## Architecture Overview

**Core Components:**
- **Server** (`noetl/server/`): FastAPI-based orchestration engine with REST APIs for catalog, events, queue, and execution coordination
- **Worker** (`noetl/worker/`): Polling workers that lease jobs from PostgreSQL queue and execute tasks
- **CLI** (`noetlctl/src/main.rs`): Rust-based command interface (binary: `noetl`) managing server/worker lifecycle, build, and K8s deployment
- **Plugins** (`noetl/tools/`): Extensible action executors (http, postgres, duckdb, python, secrets, etc.)
- **Observability** (`ci/manifests/clickhouse/`): ClickHouse-based observability stack with OpenTelemetry schema for logs, metrics, and traces

**Data Flow:**
1. Playbooks (YAML) → Catalog registration → Event-driven execution
2. Server evaluates next steps → Enqueues jobs → Workers execute → Report back via events
3. All state persisted in PostgreSQL event log for reconstruction and coordination
4. Observability data flows to ClickHouse for analytics and AI agent access via MCP server

## Development Workflows

**Setup & Testing:**
```bash
task bring-all                                      # Complete K8s dev environment (build + deploy all components)
task deploy-postgres                                # Deploy PostgreSQL to kind cluster
task deploy-noetl                                   # Deploy NoETL server and workers
task observability:activate-all                     # Deploy ClickHouse, Qdrant, NATS
task pagination-server:test:pagination-server:full  # Deploy pagination test server
task test:regression:full                           # Complete regression test suite (setup + run)
task test-*-full                                    # Integration tests (register credentials, playbook, execute)
```

**Local Development (Rust CLI Recommended):**
```bash
# Build and deployment
noetl build [--no-cache]       # Build Docker image with Rust CLI
noetl k8s deploy               # Deploy to kind cluster (auto-loads image)
noetl k8s redeploy             # Rebuild and redeploy
noetl k8s reset                # Full reset: schema + redeploy + test setup
noetl k8s remove               # Remove NoETL from cluster

# Server/Worker management (local)
noetl server start [--init-db] # Start FastAPI server
noetl server stop [--force]    # Stop server
noetl worker start             # Start worker (v2 architecture default)
noetl worker stop              # Stop worker

# Database management
noetl db init                  # Initialize database schema
noetl db validate              # Validate database schema

# Legacy task commands (still available)
task docker-build-noetl              # Build NoETL container image
task kind-create-cluster             # Create kind Kubernetes cluster
task test-cluster-health             # Check cluster health and endpoints
task clear-all-cache                 # Clear local file cache
task observability:status-all        # Check all observability services
task observability:health-all        # Health check all services
```

## Project-Specific Patterns

**Playbook Structure** (core abstraction):
```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:                 # Required metadata section
  name: playbook_name     # Unique identifier
  path: catalog/path      # Catalog registration path
workload:                 # Global variables merged with payload; Jinja2 templated
  variable: value
workbook:                 # Named reusable tasks (optional)
  - name: task_name       # Reference name
    tool: python          # Action type: python, http, postgres, duckdb, playbook, iterator
    code: |               # Type-specific configuration
      def main(input_data):
        return result
    sink:                 # Optional: save task result to storage
      tool: postgres
      table: table_name
workflow:                 # Execution flow (required, must have 'start' step)
  - step: start           # Required entry point
    desc: description
    next:                 # Conditional routing
      - when: "{{ condition }}"
        then:
          - step: next_step
        args:             # Args to pass to next steps
          key: "{{ value }}"
  - step: task_step
    tool: workbook        # Reference workbook task by name
    name: task_name       # OR inline action tool: python, http, postgres, etc.
    args:                 # Args passed to action via Jinja2 templating
      input: "{{ workload.variable }}"
    next:
      - step: end
  - step: end
    desc: End workflow
```

**Key Concepts:**
- **Jinja2 Templating**: All string values support Jinja2 with access to:
  - `{{ workload.field }}` - Global workflow variables
  - `{{ vars.var_name }}` - Stored variables extracted via vars blocks
  - `{{ step_name.field }}` - Previous step results (server normalizes by extracting `.data` if present)
  - `{{ result.field }}` - Current step result (used in vars block for extraction)
  - `{{ execution_id }}` - Current execution identifier
- **Variable Extraction**: Use `vars:` block at step level to declaratively extract values from step results:
  ```yaml
  - step: fetch_data
    tool: postgres
    query: "SELECT user_id, email FROM users LIMIT 1"
    vars:
      user_id: "{{ result[0].user_id }}"  # Extract from current step result
      email: "{{ result[0].email }}"
    next:
    - step: process
  
  - step: process
    tool: python
    args:
      user_id: "{{ vars.user_id }}"  # Access extracted variable
      email: "{{ vars.email }}"
  ```
- **Workflow Entry**: Must have a step named "start" as the workflow entry point
- **Step Types**:
  - `tool: workbook` - References named task from workbook section by `name` attribute
  - Direct action tools: `python`, `http`, `postgres`, `duckdb`, `playbook`, `iterator`
- **Conditional Flow**: Steps use `next` with optional `when` conditions and `then` arrays for routing
  - `next:` - Provides default/fallback routing edges; always evaluated when present
  - `case:` - Optional conditional routing (v2 DSL); when conditions don't match, engine falls back to `next:` field
  - **Pattern**: Use `next:` for unconditional default flow, `case:` for event-driven or conditional branching
- **Iterator**: `tool: iterator` loops over collections with `collection`, `element`, and `mode` (sequential/async) attributes
- **HTTP Pagination**: `loop.pagination` enables automatic page continuation with `continue_while`, `next_page`, and `merge_strategy` attributes
  ```yaml
  - step: fetch_all_data
    tool: http
    url: "{{ api_url }}/data"
    params:
      page: 1
    loop:
      pagination:
        type: response_based
        continue_while: "{{ response.data.paging.hasMore }}"
        next_page:
          params:
            page: "{{ (response.data.paging.page | int) + 1 }}"
        merge_strategy: append
        merge_path: data.data
        max_iterations: 100
  ```
  **Note**: HTTP responses are wrapped as `{id, status, data: <api_response>}`, so use `response.data.*` for API fields and `merge_path: data.data` for nested data arrays.
- **Save Blocks**: Any action can have a `save` attribute to persist results to storage backends
- **Playbook Composition**: `type: playbook` allows calling sub-playbooks with `path` and `return_step` attributes

**Credential Patterns** (v1.0+ unified auth):
- `auth: {type: postgres, credential: key}` - Single credential lookup
- `credentials: {alias: {key: credential_name}}` - Multiple credential binding
- `secret: "{{ secret.NAME }}"` - External secret manager resolution

**Script Attribute** (External Code Execution - ADF-aligned):
All action tools support loading code from external sources (GCS, S3, file, HTTP) similar to Azure Data Factory's linked services:
```yaml
script:
  uri: gs://bucket-name/scripts/transform.py  # Full URI with scheme
  source:
    type: file|gcs|s3|http           # Source type
    # Source-specific fields:
    region: aws-region                # For s3 (optional)
    auth: credential-reference        # For gcs/s3 authentication
    endpoint: https://url             # For http (base URL)
    method: GET                       # For http (default: GET)
    headers: {}                       # For http
    timeout: 30                       # For http (seconds)
```

**Priority Order**: `script` > `code_b64`/`command_b64` > `code`/`command`

**Supported Plugins**: python, postgres, duckdb, snowflake, http

**URI Formats**:
- GCS: `gs://bucket-name/path/to/script.py` (required format)
- S3: `s3://bucket-name/path/to/script.sql` (required format)
- File: `./scripts/transform.py` or `/abs/path/script.py`
- HTTP: Relative path with `source.endpoint` or full URL

**Examples**:
```yaml
# Python with GCS
- step: transform
  tool: python
  script:
    uri: gs://data-pipelines/scripts/transform.py
    source:
      type: gcs
      auth: gcp_service_account

# Postgres with S3
- step: migration
  tool: postgres
  auth: pg_prod
  script:
    uri: s3://sql-scripts/migrations/v2.5/upgrade.sql
    source:
      type: s3
      region: us-west-2
      auth: aws_credentials

# Python with file source
- step: local_script
  tool: python
  script:
    uri: ./scripts/transform.py
    source:
      type: file

# Python with HTTP source
- step: fetch_script
  tool: python
  script:
    uri: transform.py
    source:
      type: http
      endpoint: https://api.example.com/scripts
      headers:
        Authorization: "Bearer {{ secret.api_token }}"
```

See `tests/fixtures/playbooks/script_execution/` and `docs/script_attribute_design.md` for complete details.

**Plugin Development** (`noetl/tools/`):
- Inherit from base classes in `base.py`
- Use `report_event()` for execution tracking
- Follow type-specific patterns in existing plugins (http.py, postgres.py, etc.)

**Event-Driven Architecture:**
- All execution state in `noetl.event` table
- Server reconstructs state from events to determine next steps
- Workers report progress via `report_event()` calls

## Key Files & Directories

**Core Logic:**
- `noetl/core/dsl/` - Playbook parsing, validation, and rendering
- `noetl/server/api/event/processing.py` - Server-side execution coordination
- `noetl/server/api/broker/core.py` - Execution engine
- `noetl/tools/` - All action type implementations

**Development Infrastructure:**
- `taskfile.yml` - Main task automation with included taskfiles for tests and monitoring
- `ci/taskfile/` - Specialized taskfiles for testing, troubleshooting, and observability
- `ci/taskfile/test-server.yml` - Pagination test server lifecycle management
- `ci/kind/config.yaml` - **Kind cluster configuration with NodePort mappings** (DO NOT use port-forward, ports are permanently mapped here)
- `tests/taskfile/noetltest.yml` - Test task definitions
- `docker/` - Container build scripts for all components
- `docker/test-server/` - Pagination test server Dockerfile
- `ci/manifests/test-server/` - Kubernetes manifests for test server
- `tests/fixtures/playbooks/` - Comprehensive test playbooks demonstrating all patterns
- `tests/fixtures/servers/paginated_api.py` - FastAPI pagination test server

**Testing:**
- Follow `test-*-full` pattern for integration tests (e.g., `task test-control-flow-workbook-full`)
- Use `tests/fixtures/playbooks/` for test scenarios
- Register test credentials with `task register-test-credentials`
- Check cluster health with `task test-cluster-health`

## Configuration

**Environment Variables:**
- `NOETL_*` prefixed settings (see `noetl/core/config.py`)
- Worker pool configuration via `NOETL_WORKER_POOL_*`
- Database connection via standard `POSTGRES_*` variables
- **Timezone**: `TZ` must match across all components (Postgres, server, worker) - default is `UTC`

**Database Access (Development):**
- **PostgreSQL Connection**:
  - JDBC URL: `jdbc:postgresql://localhost:54321/demo_noetl`
  - User: `demo` / Password: `demo` (application data)
  - User: `noetl` / Password: `noetl` (NoETL metadata schema)
  - Schema: `noetl` (for NoETL system tables: catalog, event, queue, etc.)
- **NoETL API for Postgres Queries**:
  - Endpoint: `POST http://localhost:8082/api/postgres/execute` (NOT 30082!)
  - Documentation: `http://localhost:8082/docs#/default/execute_postgres_api_postgres_execute_post`
  - **Use this REST API instead of running `psql` commands directly**
  - Request body examples:
    ```json
    {
      "query": "SELECT * FROM noetl.catalog LIMIT 5",
      "connection_string": "postgresql://demo:demo@localhost:54321/demo_noetl"
    }
    ```
    Or with schema parameter:
    ```json
    {
      "query": "SELECT execution_id, status FROM event WHERE execution_id = 123",
      "schema": "noetl"
    }
    ```
  - Response format:
    ```json
    {
      "status": "ok",
      "result": [{"column": "value"}]
    }
    ```
  - Supports query parameters: `query`, `query_base64`, `procedure`, `parameters`, `schema`, `connection_string`

**Deployment Modes:**
- Local: Direct Python execution with file-based logs
- Docker: Containerized with environment-based configuration
- Kubernetes: Helm charts with unified observability stack (Grafana, VictoriaMetrics, ClickHouse)

**Kind Cluster Port Mappings (CRITICAL):**
- **Port mappings are PERMANENT** - defined in `ci/kind/config.yaml`
- **DO NOT use `kubectl port-forward`** - ports are already mapped to localhost
- **Use localhost ports directly**: 
  - NoETL API: `http://localhost:8082` (maps to NodePort 30082)
  - Postgres: `localhost:54321` (maps to NodePort 30321)
  - ClickHouse HTTP: `localhost:30123` (maps to NodePort 30123)
  - Test Server: `localhost:30555` (maps to NodePort 30555)
- See `ci/kind/config.yaml` for complete port mapping list
- After rebuilding containers, ports remain the same - no need to re-map

**Observability Stack:**
- **ClickHouse**: Column-oriented database for logs, metrics, and traces (OpenTelemetry format)
  - Access: HTTP (NodePort 30123), Native (NodePort 30900), MCP (port 8124)
  - Tables: `observability.logs`, `observability.metrics`, `observability.traces`, `observability.noetl_events`
- **Qdrant**: Vector database for embeddings and semantic search
  - Access: HTTP (NodePort 30633), gRPC (NodePort 30634)
  - Features: Vector similarity search, extended filtering, 5GB storage
- **NATS JetStream**: Messaging and key-value store for event-driven workflows
  - Access: Client (NodePort 30422), Monitoring (NodePort 30822)
  - Features: Stream persistence, KV store, credentials (noetl/noetl)
- **Commands**: 
  - `task observability:activate-all` / `task observability:deactivate-all`
  - Individual: `task clickhouse:deploy`, `task qdrant:deploy`, `task nats:deploy`
- **Documentation**: See `docs/observability_services.md` for complete guide

**Test Infrastructure:**
- **Pagination Test Server**: FastAPI server for testing HTTP pagination patterns
  - Access: ClusterIP (paginated-api.test-server.svc.cluster.local:5555), NodePort (localhost:30555)
  - Endpoints: `/api/v1/assessments` (page-based), `/api/v1/users` (offset-based), `/api/v1/events` (cursor-based), `/api/v1/flaky` (retry testing)
  - Commands:
    - Deploy: `task pagination-server:test:pagination-server:full`
    - Status: `task pagination-server:test:pagination-server:status`
    - Test: `task pagination-server:test:pagination-server:test`
    - Logs: `task pagination-server:test:pagination-server:logs`
  - Configuration: `ci/manifests/test-server/`, `docker/test-server/Dockerfile`

**Timezone Configuration** (CRITICAL):
- **Default**: UTC for all components (Postgres, server, worker)
- **Requirement**: `TZ` environment variable must match between database and application
- **Python Code**: Always use timezone-aware datetimes: `datetime.now(timezone.utc)`
- **Never Use**: `datetime.utcnow()` or `datetime.now()` without timezone - causes timestamp offset bugs
- **Config Files**: 
  - `ci/manifests/postgres/configmap.yaml` - Postgres TZ
  - `ci/manifests/noetl/configmap.yaml` - Server/Worker TZ
  - `docker/postgres/Dockerfile` - Container TZ
- **Documentation**: See `docs/timezone_configuration.md` for complete guide

## API Development Standards

**Pydantic Models (REQUIRED):**
- **Every API endpoint MUST use Pydantic models** for request and response schemas
- **Never use** raw dictionaries, `dict[str, Any]`, or untyped responses
- Create dedicated schema file (`schema.py`) in each API module
- Use `response_model` parameter on all endpoint decorators
- Include `Field()` with descriptions for all model attributes

**API Module Structure:**
```
noetl/server/api/{module}/
├── __init__.py          # Export router
├── schema.py            # Pydantic models (REQUIRED)
└── endpoint.py          # FastAPI routes
```

**Example Pattern (from vars API):**
```python
# schema.py
from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime

class VariableMetadata(BaseModel):
    """Variable with full metadata."""
    value: Any = Field(..., description="Variable value (JSON-serializable)")
    type: str = Field(..., description="Variable type: user_defined, step_result, computed, iterator_state")
    source_step: Optional[str] = Field(None, description="Step that created/updated the variable")
    created_at: datetime = Field(..., description="Creation timestamp")
    accessed_at: datetime = Field(..., description="Last access timestamp")
    access_count: int = Field(..., description="Number of times variable was read")

class VariableListResponse(BaseModel):
    """Response for GET /api/vars/{execution_id}."""
    execution_id: int = Field(..., description="Execution identifier")
    variables: dict[str, VariableMetadata] = Field(..., description="Variables with metadata")
    count: int = Field(..., description="Total variable count")

class SetVariablesRequest(BaseModel):
    """Request body for POST /api/vars/{execution_id}."""
    variables: dict[str, Any] = Field(..., description="Variables to set")
    var_type: str = Field(default="user_defined", description="Variable type")
    source_step: Optional[str] = Field(None, description="Optional source step")

# endpoint.py
@router.get("/{execution_id}", response_model=VariableListResponse)
async def list_variables(
    execution_id: int = Path(..., description="Execution ID")
) -> VariableListResponse:
    """Get all variables with metadata."""
    # ... implementation
    return VariableListResponse(
        execution_id=execution_id,
        variables=variables,
        count=len(variables)
    )
```

**Benefits:**
- Automatic OpenAPI/Swagger documentation generation
- Request/response validation at API boundaries
- Type safety and IDE autocomplete
- Clear contract definition for API consumers
- Prevents runtime type errors

## Writing Style Guidelines

**Prohibited Words and Phrases:**
- Never use "comprehensive" - use specific, descriptive alternatives like "complete", "full", "detailed", "thorough"
- Never use "ensure" - use direct action words like "verify", "check", "validate", "confirm", "guarantee"
- **Never use emojis** in any code, scripts, documentation, code comments, task descriptions, echo statements, or log messages
- Prefer concise, clear descriptions over verbose explanations

**Examples:**
- ❌ "Comprehensive test suite that ensures all functionality works"
- ✅ "Complete test suite that validates all functionality"
- ❌ "Deploy comprehensive monitoring stack 🚀"  
- ✅ "Deploy complete monitoring stack"

When working with this codebase, prioritize understanding the event-driven execution model and the playbook → events → worker execution flow. The architecture is designed for distributed execution with careful state management through Postgres system state storage.

## Current Development Focus

**Active Task: Token-Based Authentication Implementation**

See `docs/token_auth_implementation.md` for detailed requirements and implementation plan. Key focus areas:

1. **Snowflake MFA/TOTP Issue**: Tests failing due to MFA requirement - need OAuth token-based auth
2. **Google OAuth Integration**: Replace gcloud CLI token fetching with Python SDK (`google.auth.transport.requests`, `google.oauth2.id_token`)
3. **HTTP Plugin Token Injection**: Support dynamic Bearer token resolution in HTTP actions
4. **Credential Schema Extension**: Add token-based credential types alongside existing password-based auth

When working on authentication, credentials, or plugin improvements, refer to the token auth implementation document for context and requirements.