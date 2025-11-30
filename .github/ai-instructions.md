# NoETL Development Guide for AI Coding Agents

NoETL is a workflow automation framework for data processing and MLOps orchestration with a distributed server-worker architecture.

## Architecture Overview

**Core Components:**
- **Server** (`noetl/server/`): FastAPI-based orchestration engine with REST APIs for catalog, events, queue, and execution coordination
- **Worker** (`noetl/worker/`): Polling workers that lease jobs from PostgreSQL queue and execute tasks
- **CLI** (`noetl/cli/ctl.py`): Typer-based command interface managing server/worker lifecycle
- **Plugins** (`noetl/plugin/`): Extensible action executors (http, postgres, duckdb, python, secrets, etc.)
- **Observability** (`ci/manifests/clickhouse/`): ClickHouse-based observability stack with OpenTelemetry schema for logs, metrics, and traces

**Data Flow:**
1. Playbooks (YAML) → Catalog registration → Event-driven execution
2. Server evaluates next steps → Enqueues jobs → Workers execute → Report back via events
3. All state persisted in PostgreSQL event log for reconstruction and coordination
4. Observability data flows to ClickHouse for analytics and AI agent access via MCP server

## Development Workflows

**Setup & Testing:**
```bash
task bring-all                    # Complete K8s dev environment (build + deploy all components)
task deploy-postgres              # Deploy PostgreSQL to kind cluster
task deploy-noetl                 # Deploy NoETL server and workers
task observability:activate-all   # Deploy ClickHouse, Qdrant, NATS
task test-*-full                  # Integration tests (register credentials, playbook, execute)
```

**Local Development:**
```bash
task docker-build-noetl          # Build NoETL container image
task kind-create-cluster         # Create kind Kubernetes cluster
task test-cluster-health         # Check cluster health and endpoints
task clear-all-cache             # Clear local file cache
task observability:status-all    # Check all observability services
task observability:health-all    # Health check all services
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
        data:             # Data to pass to next steps
          key: "{{ value }}"
  - step: task_step
    type: workbook        # Reference workbook task by name
    name: task_name       # OR inline action type: python, http, postgres, etc.
    data:                 # Data passed to action via Jinja2 templating
      input: "{{ workload.variable }}"
    next:
      - step: end
  - step: end
    desc: End workflow
```

**Key Concepts:**
- **Jinja2 Templating**: All string values support Jinja2 with access to `workload`, `execution_id`, step results (e.g., `{{ step_name.data }}`), and iterator context
- **Workflow Entry**: Must have a step named "start" as the workflow entry point
- **Step Types**:
  - `type: workbook` - References named task from workbook section by `name` attribute
  - Direct action types: `python`, `http`, `postgres`, `duckdb`, `playbook`, `iterator`
- **Conditional Flow**: Steps use `next` with optional `when` conditions and `then` arrays for routing
- **Iterator**: `type: iterator` loops over collections with `collection`, `element`, and `mode` (sequential/async) attributes
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

**Plugin Development** (`noetl/plugin/`):
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
- `noetl/plugin/` - All action type implementations

**Development Infrastructure:**
- `taskfile.yml` - Main task automation with included taskfiles for tests and monitoring
- `ci/taskfile/` - Specialized taskfiles for testing, troubleshooting, and observability
- `tests/taskfile/noetltest.yml` - Test task definitions
- `docker/` - Container build scripts for all components
- `tests/fixtures/playbooks/` - Comprehensive test playbooks demonstrating all patterns

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

**Deployment Modes:**
- Local: Direct Python execution with file-based logs
- Docker: Containerized with environment-based configuration
- Kubernetes: Helm charts with unified observability stack (Grafana, VictoriaMetrics, ClickHouse)

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

## Writing Style Guidelines

**Prohibited Words and Phrases:**
- Never use "comprehensive" - use specific, descriptive alternatives like "complete", "full", "detailed", "thorough"
- Never use "ensure" - use direct action words like "verify", "check", "validate", "confirm", "guarantee"
- Never use emojis in any scripts, documentation, code comments, or task descriptions
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