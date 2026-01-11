# NoETL Automation Playbooks

This directory contains NoETL playbooks for automating development, CI/CD, and testing workflows. These playbooks provide an alternative to Taskfile/Makefile commands, allowing you to manage infrastructure as code using NoETL's own DSL.

## Directory Structure

```
automation/
├── main.yaml                  # Main entry point with routing to sub-workflows
├── setup/                     # Environment setup and teardown
│   ├── bootstrap.yaml         # Complete environment bootstrap
│   └── destroy.yaml           # Environment cleanup
├── infrastructure/            # Infrastructure component management
│   ├── postgres.yaml          # PostgreSQL deployment and management
│   ├── qdrant.yaml            # Qdrant vector database management
│   └── monitoring.yaml        # VictoriaMetrics monitoring stack
├── test/                      # Testing workflows
│   ├── pagination-server.yaml # Pagination test server automation
│   ├── setup.yaml             # Test environment setup
│   ├── regression.yaml        # Run regression test suite
│   └── integration.yaml       # Integration test execution
├── ci/                        # CI/CD workflows
│   ├── build.yaml             # Build Docker images and binaries
│   ├── deploy.yaml            # Deployment workflows
│   └── quick_dev.yaml         # Fast development cycle
└── examples/                  # Example playbooks (existing)
```

## Usage

### Quick Start

Replace `make` and `task` commands with NoETL playbooks:

```bash
# Old way
make destroy && make bootstrap
task bring-all

# New way
noetl run automation/setup/destroy
noetl run automation/setup/bootstrap

# Or use main entry point
noetl run automation/main destroy
noetl run automation/main bootstrap
```

### Main Entry Point

The `main.yaml` playbook routes to different workflows:

```bash
# Show help
noetl run automation/main help

# Bootstrap environment
noetl run automation/main bootstrap

# Destroy environment
noetl run automation/main destroy

# Quick development cycle
noetl run automation/main dev
```

### Individual Workflows

#### Setup Workflows

**Bootstrap Complete Environment:**
```bash
noetl run automation/setup/bootstrap
```

Equivalent to:
- `./ci/bootstrap/bootstrap.sh`
- `task bring-all`

Steps performed:
1. Verify dependencies (Docker, kubectl, kind, task)
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
noetl run automation/setup/destroy
```

Equivalent to: `make destroy`

Steps performed:
1. Delete kind cluster
2. Clean Docker resources (images, volumes, builders)
3. Clear local cache directories
4. Clear NoETL data and logs

#### CI/CD Workflows

**Build Images:**
```bash
noetl run automation/ci/build
```

Steps:
- Build noetlctl CLI
- Build NoETL Docker image
- Load image to kind cluster

**Deploy to Kubernetes:**
```bash
noetl run automation/ci/deploy
```

Steps:
- Deploy PostgreSQL
- Deploy NoETL
- Deploy monitoring (optional)

**Quick Development Cycle:**
```bash
noetl run automation/ci/quick_dev
```

Equivalent to: `task dev`

Steps:
- Build NoETL image
- Reload to kind
- Redeploy pods

#### Test Workflows

**Setup Test Environment:**
```bash
noetl run automation/test/setup
```

Equivalent to: `task test:k8s:setup-environment`

Steps:
- Reset database schema
- Register test credentials
- Register test playbooks
- Create test tables

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

Equivalent task commands:
- `task pagination-server:tpsb` → `--set action=build`
- `task pagination-server:tpsd` → `--set action=deploy`
- `task pagination-server:tpsf` → `--set action=full`
- `task pagination-server:tpss` → `--set action=status`
- `task pagination-server:tpst` → `--set action=test`

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

Equivalent task commands:
- `task postgres:k8s:deploy` → `--set action=deploy`
- `task postgres:k8s:remove` → `--set action=remove`
- `task postgres:k8s:schema-reset` → `--set action=schema-reset`
- `task postgres:local:clear-cache` → `--set action=clear-cache`

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

Equivalent task commands:
- `task qdrant:deploy` → `--set action=deploy`
- `task qdrant:undeploy` → `--set action=undeploy`
- `task qdrant:status` → `--set action=status`
- `task qdrant:health` → `--set action=health`
- `task qdrant:test` → `--set action=test`
- `task qdrant:collections` → `--set action=collections`
- `task qdrant:restart` → `--set action=restart`

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

Equivalent task commands:
- `task nats:deploy` → `--set action=deploy`
- `task nats:undeploy` → `--set action=undeploy`
- `task nats:status` → `--set action=status`
- `task nats:health` → `--set action=health`
- `task nats:streams` → `--set action=streams`
- `task nats:monitoring` → `--set action=monitoring`
- `task nats:connect` → `--set action=connect`
- `task nats:test` → `--set action=test`
- `task nats:restart` → `--set action=restart`

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

Equivalent task commands:
- `task observability:activate-all` → `--set action=activate-all`
- `task observability:deactivate-all` → `--set action=deactivate-all`
- `task observability:status-all` → `--set action=status-all`
- `task observability:health-all` → `--set action=health-all`
- `task observability:restart-all` → `--set action=restart-all`

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

Equivalent task commands:
- `task monitoring:k8s:deploy` → `--set action=deploy`
- `task monitoring:k8s:delete-stack` → `--set action=undeploy`
- `task monitoring:k8s:grafana-creds` → `--set action=grafana-creds`
- `task monitoring:k8s:deploy-dashboards` → `--set action=deploy-dashboards`
- `task monitoring:k8s:deploy-exporter` → `--set action=deploy-exporter`
- `task monitoring:k8s:deploy-noetl-scrape` → `--set action=deploy-noetl-scrape`
- `task monitoring:k8s:deploy-vector` → `--set action=deploy-vector`
- `task monitoring:k8s:deploy-vmlogs` → `--set action=deploy-vmlogs`

**Run Regression Tests:**
```bash
noetl run automation/test/regression
```

Equivalent to: `task test:regression:full`

Steps:
- Setup test environment
- Execute regression test suite
- Collect results

## Migration from Taskfile

### Command Mapping

| Taskfile Command | NoETL Playbook |
|-----------------|----------------|
| `task bring-all` | `noetl run automation/setup/bootstrap` |
| `make destroy` | `noetl run automation/setup/destroy` |
| `task dev` | `noetl run automation/ci/quick_dev` |
| `task test:k8s:setup-environment` | `noetl run automation/test/setup` |
| `task test:regression:full` | `noetl run automation/test/regression` |
| `task docker:local:noetl-image-build` | `noetl run automation/ci/build` |
| `task noetl:k8s:deploy` | `noetl run automation/ci/deploy` |

### Benefits of Playbook-Based Automation

1. **Infrastructure as Code**: All automation workflows are versioned NoETL playbooks
2. **Observability**: Execution tracked in NoETL event log and observability stack
3. **Composability**: Chain playbooks together using `kind: playbook`
4. **Conditional Logic**: Use Jinja2 templating for dynamic workflows
5. **Error Handling**: Built-in retry and error handling patterns
6. **Self-Documenting**: YAML DSL is more readable than shell scripts

### Gradual Migration

You can use both approaches simultaneously:

```bash
# Mix Taskfile and playbooks
task bring-all                           # Use existing task
noetl run automation/test/regression     # Use new playbook

# Playbooks can call task commands internally
# See bootstrap.yaml for subprocess execution examples
```

## Development

### Adding New Automation Workflows

1. Create playbook in appropriate directory (`setup/`, `ci/`, `test/`)
2. Follow existing patterns for error handling and status reporting
3. Use `kind: python` with `subprocess` module to call existing `task` commands
4. Document in this README

### Playbook Patterns

**Call Task Command:**
```yaml
- step: run_task
  tool:
    kind: python
    libs:
      subprocess: subprocess
    code: |
      proc = subprocess.run(
          ["task", "some:task:name"],
          capture_output=True,
          text=True
      )
      
      result = {
          "status": "success" if proc.returncode == 0 else "error",
          "data": {
              "returncode": proc.returncode,
              "message": "Task completed" if proc.returncode == 0 else "Task failed"
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
- [ ] Add `automation/observability/` for observability stack management
- [ ] Add `automation/monitoring/` for monitoring stack workflows
- [ ] Create `automation/gateway/` for Gateway API workflows
- [ ] Add parallel execution for independent tasks
- [ ] Implement approval gates for production deployments

## See Also

- [Taskfile Documentation](../../ci/taskfile/README.md)
- [Bootstrap Documentation](../../ci/bootstrap/README.md)
- [NoETL DSL Reference](https://noetl.dev/docs/reference/dsl/)
