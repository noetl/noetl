# NoETL Development Guide for AI Coding Agents

NoETL is a workflow automation framework for data processing and MLOps orchestration with a distributed server-worker architecture.

## Architecture Overview

**Core Components:**
- **Server** (`noetl/server/`): FastAPI-based orchestration engine with REST APIs for catalog, events, queue, and execution coordination
- **Worker** (`noetl/worker/`): Polling workers that lease jobs from PostgreSQL queue and execute tasks
- **CLI** (`noetl/cli/ctl.py`): Typer-based command interface managing server/worker lifecycle
- **Plugins** (`noetl/plugin/`): Extensible action executors (http, postgres, duckdb, python, secrets, etc.)

**Data Flow:**
1. Playbooks (YAML) → Catalog registration → Event-driven execution
2. Server evaluates next steps → Enqueues jobs → Workers execute → Report back via events
3. All state persisted in PostgreSQL event log for reconstruction and coordination

## Development Workflows

**Setup & Testing:**
```bash
task bring-all            # Complete K8s dev environment (build + deploy all components)
task deploy-postgres      # Deploy PostgreSQL to kind cluster
task deploy-noetl         # Deploy NoETL server and workers
task test-*-full         # Integration tests (register credentials, playbook, execute)
```

**Local Development:**
```bash
task docker-build-noetl   # Build NoETL container image
task kind-create-cluster  # Create kind Kubernetes cluster
task test-cluster-health  # Check cluster health and endpoints
task clear-all-cache     # Clear local file cache
```

## Project-Specific Patterns

**Playbook Structure** (core abstraction):
```yaml
apiVersion: noetl.io/v1
kind: Playbook
workload:                 # Input parameters (readonly, Jinja2 templated)
workflow:                 # Ordered steps with conditional flow
  - step: name
    type: plugin_type     # http, postgres, duckdb, python, workbook, etc.
    data: {}             # Step-specific parameters
    next:                 # Conditional transitions
      - when: "{{ condition }}"
        then: [steps]
workbook:                 # Reusable task definitions
```

**Credential Patterns** (v1.0+ unified auth):
- `auth: {type: postgres, credential: key}` - Single credential lookup
- `credentials: {alias: {key: credential_name}}` - Multiple credential binding
- `secret: "{{ secret.NAME }}"` - External secret manager resolution

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
- `examples/` - Reference playbooks demonstrating patterns

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

**Deployment Modes:**
- Local: Direct Python execution with file-based logs
- Docker: Containerized with environment-based configuration
- Kubernetes: Helm charts with unified observability stack (Grafana, VictoriaMetrics)

When working with this codebase, prioritize understanding the event-driven execution model and the playbook → events → worker execution flow. The architecture is designed for distributed execution with careful state management through Postgres system state storage.