# NoETL Automation Playbooks

This directory contains NoETL playbooks for automating development, CI/CD, and testing workflows. These playbooks allow you to manage infrastructure as code using NoETL's own DSL.

## Runtime Modes

NoETL playbooks can execute in two modes:

| Runtime | Description | Requirements |
|---------|-------------|--------------|
| **local** | Rust interpreter, no server | Just the `noetl` binary |
| **distributed** | Server-worker architecture | PostgreSQL, NoETL server/worker |

All playbooks in this directory use **local runtime** by default and include the `executor` section:

```yaml
executor:
  profile: local           # Use local Rust interpreter
  version: noetl-runtime/1 # Runtime version
```

## Directory Structure

```
automation/
├── main.yaml                  # Main entry point with routing to sub-workflows
├── boot.yaml                  # Quick bootstrap alias
├── destroy.yaml               # Quick destroy alias
├── setup/                     # Environment setup and teardown
│   ├── bootstrap.yaml         # Complete environment bootstrap
│   └── destroy.yaml           # Environment cleanup
├── infrastructure/            # Infrastructure component management
│   ├── postgres.yaml          # PostgreSQL deployment and management
│   ├── qdrant.yaml            # Qdrant vector database management
│   ├── nats.yaml              # NATS JetStream messaging
│   ├── clickhouse.yaml        # ClickHouse analytics database
│   ├── monitoring.yaml        # VictoriaMetrics monitoring stack
│   ├── observability.yaml     # Aggregate observability operations
│   └── kind.yaml              # Kind Kubernetes cluster management
├── development/               # Development workflows
│   ├── noetl.yaml             # NoETL server/worker management
│   ├── docker.yaml            # Docker image building
│   ├── setup_tooling.yaml     # OS-aware tooling setup (auto-detects OS)
│   ├── tooling_macos.yaml     # Development tool setup for macOS (Homebrew)
│   └── tooling_linux.yaml     # Development tool setup for Linux/WSL2 (apt-get)
├── test/                      # Testing workflows
│   └── pagination-server.yaml # Pagination test server automation
├── iap/                       # Infrastructure as Playbook
│   └── gcp/                   # GCP provider playbooks
│       ├── gke_autopilot.yaml # GKE Autopilot cluster management
│       ├── state_sync.yaml    # State synchronization
│       └── init_state_bucket.yaml # Initialize GCS state bucket
└── examples/                  # Example playbooks
    ├── http_example.yaml      # HTTP request examples
    ├── parent_playbook.yaml   # Playbook composition
    └── conditional_flow.yaml  # Conditional routing
```

## Usage

### Quick Start

```bash
# Destroy and rebuild environment
noetl run automation/setup/destroy.yaml && noetl run automation/setup/bootstrap.yaml

# Or use the shorthand aliases
noetl run destroy && noetl run boot
```

### Main Entry Point

The `main.yaml` playbook routes to different workflows:

```bash
# Show help
noetl run automation/main.yaml --set target=help

# Bootstrap environment
noetl run automation/main.yaml --set target=bootstrap

# Destroy environment
noetl run automation/main.yaml --set target=destroy

# Quick development cycle
noetl run automation/main.yaml --set target=dev
```

### Individual Workflows

#### Setup Workflows

**Bootstrap Complete Environment:**
```bash
noetl run automation/setup/bootstrap.yaml
```

Steps performed:
1. Verify dependencies (Docker, kubectl, kind)
2. Check ports availability (54321, 3000, 9428, 8082)
3. Build noetlctl Rust CLI
4. Build NoETL Docker image
5. Create kind Kubernetes cluster
6. Load image into kind
7. Deploy PostgreSQL
8. Deploy observability stack (ClickHouse, Qdrant, NATS)
9. Deploy monitoring stack (VictoriaMetrics, Grafana)
10. Deploy NoETL server and workers

**Destroy Environment:**
```bash
noetl run automation/setup/destroy.yaml
```

Steps performed:
1. Delete kind cluster
2. Clean Docker resources (images, volumes, builders)
3. Clear local cache directories
4. Clear NoETL data and logs

#### Infrastructure Component Management

**PostgreSQL:**
```bash
# Deploy PostgreSQL
noetl run automation/infrastructure/postgres.yaml --set action=deploy

# Check status
noetl run automation/infrastructure/postgres.yaml --set action=status

# Reset schema
noetl run automation/infrastructure/postgres.yaml --set action=schema-reset

# View logs
noetl run automation/infrastructure/postgres.yaml --set action=logs

# Remove PostgreSQL
noetl run automation/infrastructure/postgres.yaml --set action=remove

# Clear cache
noetl run automation/infrastructure/postgres.yaml --set action=clear-cache
```

**Qdrant Vector Database:**
```bash
# Deploy Qdrant
noetl run automation/infrastructure/qdrant.yaml --set action=deploy

# Check status
noetl run automation/infrastructure/qdrant.yaml --set action=status

# Check health
noetl run automation/infrastructure/qdrant.yaml --set action=health

# Test with sample collection
noetl run automation/infrastructure/qdrant.yaml --set action=test

# List collections
noetl run automation/infrastructure/qdrant.yaml --set action=collections

# View logs
noetl run automation/infrastructure/qdrant.yaml --set action=logs

# Restart Qdrant
noetl run automation/infrastructure/qdrant.yaml --set action=restart

# Remove Qdrant
noetl run automation/infrastructure/qdrant.yaml --set action=undeploy
```

**NATS JetStream:**
```bash
# Deploy NATS
noetl run automation/infrastructure/nats.yaml --set action=deploy

# Check status
noetl run automation/infrastructure/nats.yaml --set action=status

# Check health
noetl run automation/infrastructure/nats.yaml --set action=health

# List JetStream streams
noetl run automation/infrastructure/nats.yaml --set action=streams

# Show monitoring dashboard
noetl run automation/infrastructure/nats.yaml --set action=monitoring

# Test connection
noetl run automation/infrastructure/nats.yaml --set action=connect

# Run integration tests
noetl run automation/infrastructure/nats.yaml --set action=test

# View logs
noetl run automation/infrastructure/nats.yaml --set action=logs

# Restart NATS
noetl run automation/infrastructure/nats.yaml --set action=restart

# Remove NATS
noetl run automation/infrastructure/nats.yaml --set action=undeploy
```

**Observability Aggregate Operations:**
```bash
# Activate all observability services (ClickHouse + Qdrant + NATS)
noetl run automation/infrastructure/observability.yaml --set action=activate-all

# Deactivate all observability services
noetl run automation/infrastructure/observability.yaml --set action=deactivate-all

# Check status of all services
noetl run automation/infrastructure/observability.yaml --set action=status-all

# Check health of all services
noetl run automation/infrastructure/observability.yaml --set action=health-all

# Restart all services
noetl run automation/infrastructure/observability.yaml --set action=restart-all
```

#### Test Workflows

**Pagination Test Server:**
```bash
# Full workflow (build + deploy + test)
noetl run automation/test/pagination-server.yaml --set action=full

# Individual actions
noetl run automation/test/pagination-server.yaml --set action=build
noetl run automation/test/pagination-server.yaml --set action=deploy
noetl run automation/test/pagination-server.yaml --set action=status
noetl run automation/test/pagination-server.yaml --set action=test
noetl run automation/test/pagination-server.yaml --set action=logs
noetl run automation/test/pagination-server.yaml --set action=undeploy
```

#### Infrastructure as Playbook (IaP)

Manage cloud infrastructure using playbooks:

```bash
# Initialize IaP state bucket
noetl iap apply automation/iap/gcp/init_state_bucket.yaml \
  --auto-approve \
  --var project_id=my-gcp-project \
  --var bucket_name=my-state-bucket

# Provision GKE Autopilot cluster
noetl iap apply automation/iap/gcp/gke_autopilot.yaml --auto-approve --var action=create

# Destroy GKE cluster
noetl iap apply automation/iap/gcp/gke_autopilot.yaml --auto-approve --var action=destroy

# Sync state to GCS
noetl iap apply automation/iap/gcp/state_sync.yaml --var action=push

# Pull state from GCS
noetl iap apply automation/iap/gcp/state_sync.yaml --var action=pull
```

See [automation/iap/gcp/README.md](iap/gcp/README.md) for detailed IaP documentation.

**VictoriaMetrics Monitoring Stack:**
```bash
# Deploy complete monitoring stack
noetl run automation/infrastructure/monitoring.yaml --set action=deploy

# Check status
noetl run automation/infrastructure/monitoring.yaml --set action=status

# Get Grafana admin credentials
noetl run automation/infrastructure/monitoring.yaml --set action=grafana-creds

# Deploy dashboards
noetl run automation/infrastructure/monitoring.yaml --set action=deploy-dashboards

# Deploy postgres exporter
noetl run automation/infrastructure/monitoring.yaml --set action=deploy-exporter

# Deploy NoETL metrics scraper
noetl run automation/infrastructure/monitoring.yaml --set action=deploy-noetl-scrape

# Deploy Vector log collector
noetl run automation/infrastructure/monitoring.yaml --set action=deploy-vector

# Deploy VictoriaLogs
noetl run automation/infrastructure/monitoring.yaml --set action=deploy-vmlogs

# Remove monitoring stack
noetl run automation/infrastructure/monitoring.yaml --set action=undeploy
```

## Benefits of Playbook-Based Automation

1. **Infrastructure as Code**: All automation workflows are versioned NoETL playbooks
2. **Observability**: Execution tracked in NoETL event log and observability stack
3. **Composability**: Chain playbooks together using `kind: playbook`
4. **Conditional Logic**: Use Jinja2 templating for dynamic workflows
5. **Error Handling**: Built-in retry and error handling patterns
6. **Self-Documenting**: YAML DSL is more readable than shell scripts

## Development

### Playbook Structure

All automation playbooks should include the `executor` section for local execution:

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: my_automation
  path: automation/my-workflow
  description: Description of the workflow

executor:
  profile: local           # All automation playbooks use local runtime
  version: noetl-runtime/1

workload:
  action: help  # Default action

workflow:
  - step: start
    desc: Route to action
    tool:
      kind: noop
    next:
      - step: show_help
        when: "{{ workload.action == 'help' }}"
      - step: do_build
        when: "{{ workload.action == 'build' }}"
      - step: show_help

  - step: show_help
    tool:
      kind: shell
      cmds:
        - |
          echo "Available actions:"
          echo "  --set action=help   Show this help"
          echo "  --set action=build  Run build"
    next:
      - step: end

  - step: do_build
    tool:
      kind: shell
      cmds:
        - docker build -t myapp:latest .
    next:
      - step: end

  - step: end
```

### Adding New Automation Workflows

1. Create playbook in appropriate directory (`setup/`, `infrastructure/`, `development/`, `test/`)
2. Follow existing patterns for error handling and status reporting
3. Use `kind: shell` for command execution or `kind: python` for complex logic
4. Document in this README

### Playbook Patterns

**Shell Command Execution:**
```yaml
- step: run_command
  tool:
    kind: shell
    cmds:
      - kubectl get pods -n noetl
      - docker ps
```

**Python Script Execution:**
```yaml
- step: run_python
  tool:
    kind: python
    libs:
      subprocess: subprocess
    code: |
      proc = subprocess.run(
          ["kubectl", "get", "pods", "-n", "noetl"],
          capture_output=True,
          text=True
      )

      result = {
          "status": "success" if proc.returncode == 0 else "error",
          "data": {
              "returncode": proc.returncode,
              "message": "Command completed" if proc.returncode == 0 else "Command failed"
          }
      }
```

**Conditional Routing:**
```yaml
next:
  - when: "{{ result.data.returncode == 0 }}"
    then:
      - step: success_handler
  - step: error_handler
```

**Chain Playbooks:**
```yaml
- step: run_sub_workflow
  tool:
    kind: playbook
    path: automation/ci/build
  next:
    - step: next_step
```

## Future Enhancements

- [ ] Replace all `subprocess` calls with native NoETL actions
- [ ] Add parallel execution for independent tasks
- [ ] Implement approval gates for production deployments
- [ ] Add more IaP providers (AWS, Azure)

## See Also

- [Command Reference](../documentation/docs/operations/command-reference.md) - Complete command reference with all actions
- [NoETL CLI Documentation](../documentation/docs/noetlctl/index.md)
- [Local Execution Guide](../documentation/docs/noetlctl/local_execution.md)
- [Infrastructure as Playbook](../documentation/docs/features/infrastructure_as_playbook.md)
- [NoETL DSL Reference](https://noetl.dev/docs/reference/dsl/)
