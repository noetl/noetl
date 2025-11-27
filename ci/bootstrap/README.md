# NoETL Bootstrap for Submodule Projects

This directory contains bootstrap scripts and taskfiles for projects that use NoETL as a git submodule.

## Overview

Projects can include NoETL as a git submodule and leverage its complete local development infrastructure including:
- Kind Kubernetes cluster
- PostgreSQL database
- VictoriaMetrics observability stack
- All NoETL development tools

## Quick Start

### 1. Add NoETL as Submodule

```bash
# In your project root
git submodule add https://github.com/noetl/noetl.git .noetl
git submodule update --init --recursive
```

### 2. Run Bootstrap

**The bootstrap script must be run first** - it installs all required tools including `task`, Docker, kubectl, and other dependencies.

```bash
# Automatic (detects macOS or WSL2/Ubuntu)
./.noetl/ci/bootstrap/bootstrap.sh

# Or specify OS explicitly
./.noetl/ci/bootstrap/bootstrap.sh --os macos
./.noetl/ci/bootstrap/bootstrap.sh --os linux
```

This will:
- Detect your OS (macOS or WSL2/Ubuntu)
- Install required system tools automatically:
  - **Docker** (auto-installs and starts if not present)
  - **task** (Taskfile automation tool) ← Required for all subsequent task commands
  - **pyenv** (Python version manager)
  - **tfenv** (Terraform version manager)
  - **uv** (Fast Python package manager)
  - kubectl, helm, kind (Kubernetes tools)
  - jq, yq (JSON/YAML processors)
  - psql (PostgreSQL client)
  - Python 3.12+
- Create Python venv combining your project + noetl dependencies
- Set up NoETL infrastructure (Kind cluster, Postgres, monitoring)
- Copy template files (.env.local, .gitignore, pyproject.toml)
- Create project directories (credentials/, playbooks/, data/, logs/, secrets/)

### 4. Configure Environment

Edit `.env.local` to customize your environment:

```bash
# The bootstrap script creates .env.local from template
# Customize database, server, worker, and service configurations
vim .env.local
```

Key configurations in `.env.local`:
- Database connection (POSTGRES_HOST, POSTGRES_PORT, etc.)
- NoETL server settings (NOETL_SERVER_HOST, NOETL_SERVER_PORT)
- Worker pool configuration (NOETL_WORKER_POOL_SIZE)
- Timezone settings (TZ - must match across all components)
- External service credentials (GCP, AWS, Azure, etc.)

### 5. Verify Setup

```bash
task bootstrap:verify
```

## Files Created by Bootstrap

The bootstrap script creates the following files in your project root:

- `.env.local` - Environment configuration (from `env-template`)
- `.gitignore` - Git ignore rules (from `gitignore-template`)
- `pyproject.toml` - Python project config (from `pyproject-template.toml`)
- `Taskfile.yml` - Task automation (from `Taskfile-bootstrap.yml`)
- `credentials/` - Directory for credential files (with README)
- `playbooks/` - Directory for your playbooks
- `data/` - Directory for data files
- `logs/` - Directory for log files
- `secrets/` - Directory for secret files

All template files are located in `noetl/ci/bootstrap/` for reference.

## Directory Structure

```
your-project/
├── Taskfile.yml                    # Your project taskfile (imports noetl tasks)
├── pyproject.toml                  # Your project dependencies
├── .env.local                      # Environment configuration
├── .venv/                          # Python venv (project + noetl)
├── playbooks/                      # Your custom playbooks
│   └── my_workflow.yaml
├── credentials/                    # Your credentials (gitignored)
│   └── my_service.json
└── .noetl/                         # NoETL submodule
    ├── ci/
    │   ├── bootstrap/              # Bootstrap scripts
    │   ├── taskfile/               # NoETL taskfiles
    │   ├── kind/                   # Kind cluster config
    │   ├── manifests/              # K8s manifests
    │   └── vmstack/                # Monitoring configs
    ├── noetl/                      # NoETL Python package
    └── taskfile.yml                # NoETL main taskfile
```

## Project Taskfile Structure

Your `Taskfile.yml` should include NoETL tasks:

```yaml
version: '3.45'

includes:
  # Import all NoETL tasks with 'noetl:' prefix
  noetl:
    taskfile: ./.noetl/taskfile.yml
    dir: ./.noetl
  
  # Import specific NoETL taskfiles
  noetl-kind:
    taskfile: ./.noetl/ci/taskfile/kind.yml
    dir: ./.noetl
    flatten: true

tasks:
  # Your project-specific tasks
  dev:setup:
    desc: Complete development environment setup
    cmds:
      - task: bootstrap:tools
      - task: bootstrap:venv
      - task: noetl:dev:k8s:bootstrap
  
  playbook:register:
    desc: Register your custom playbooks
    cmds:
      - .venv/bin/noetl register playbooks/my_workflow.yaml
```

## Python Environment

### Combining Dependencies

Create `pyproject.toml` in your project root:

```toml
[project]
name = "my-project"
version = "0.1.0"
dependencies = [
    # Your project dependencies
    "pandas>=2.0.0",
    "scikit-learn>=1.3.0",
    
    # Include noetl
    "-e ./.noetl",
]
```

### Virtual Environment Setup

The bootstrap script creates `.venv` with both your dependencies and NoETL:

```bash
# Automatic (via bootstrap)
./noetl/ci/bootstrap/bootstrap.sh

# Manual
python3 -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e ./.noetl
pip install -e .
```

## System Requirements

### macOS

Required tools (bootstrap installs automatically):
- Homebrew (auto-installed if not present)
- **Docker** (auto-installed via Homebrew, auto-starts Docker Desktop)
- **pyenv** (Python version manager)
- **tfenv** (Terraform version manager)
- **uv** (Fast Python package manager via curl)
- Python 3.12+
- kubectl, helm, kind, jq, yq, task, postgresql-client

**Note:** If Docker Desktop is not installed, the script will install it via Homebrew and attempt to start it automatically.

### WSL2/Ubuntu

Required tools (bootstrap installs automatically):
- **Docker Engine** (auto-installed via apt if not present)
- **pyenv** (Python version manager via pyenv.run)
- **tfenv** (Terraform version manager via git)
- **uv** (Fast Python package manager via curl)
- Python 3.12+
- kubectl, helm, kind, jq, yq, task, postgresql-client
- build-essential, git, curl

**Note:** On Linux/WSL2, the script installs Docker Engine (not Docker Desktop) and configures permissions automatically.

## Bootstrap Options

```bash
./.noetl/ci/bootstrap/bootstrap.sh [OPTIONS]

Options:
  --os {macos|linux}     Operating system (auto-detected if not specified)
  --skip-tools           Skip system tool installation
  --skip-venv            Skip Python venv setup
  --skip-cluster         Skip Kind cluster creation
  --venv-path PATH       Custom venv path (default: .venv)
  --help                 Show this help message
```

## Task Reference

Bootstrap provides these tasks:

```bash
# System setup
task bootstrap:verify          # Verify all tools installed
task bootstrap:tools           # Install system tools
task bootstrap:venv            # Create Python venv

# NoETL infrastructure (via noetl: prefix)
task noetl:dev:k8s:bootstrap   # Full K8s setup (cluster + all services)
task noetl:kind:local:cluster-create      # Create Kind cluster
task noetl:postgres:k8s:deploy            # Deploy PostgreSQL
task noetl:monitoring:k8s:deploy          # Deploy monitoring stack
task noetl:noetl:k8s:deploy               # Deploy NoETL server/workers

# Cleanup
task noetl:kind:local:cluster-delete      # Delete Kind cluster
task noetl:cache:local:clear-all          # Clear local cache
```

## Development Workflow

### 1. Start Infrastructure

```bash
# Full setup (first time)
task noetl:dev:k8s:bootstrap

# Or incremental
task noetl:kind:local:cluster-create
task noetl:postgres:k8s:deploy
task noetl:noetl:k8s:deploy
```

### 2. Register Credentials

```bash
# Create credential file
cat > credentials/my_service.json <<EOF
{
  "name": "my_service",
  "type": "postgres",
  "data": {
    "host": "localhost",
    "port": 5432,
    "user": "myuser",
    "password": "mypass",
    "database": "mydb"
  }
}
EOF

# Register with NoETL
.venv/bin/noetl register credentials/my_service.json \
  --host localhost --port 8083
```

### 3. Register Playbooks

```bash
# Register from your project
.venv/bin/noetl register playbooks/my_workflow.yaml \
  --host localhost --port 8083

# Execute
.venv/bin/noetl execute playbook my_workflow \
  --host localhost --port 8083
```

### 4. Access Services

```bash
# NoETL UI
open http://localhost:8083

# Grafana (monitoring)
kubectl port-forward -n vmstack svc/vmstack-grafana 3000:80
open http://localhost:3000

# PostgreSQL
kubectl port-forward -n postgres svc/postgres 5432:5432
psql -h localhost -U noetl -d noetl
```

## Extending NoETL Infrastructure

### Add Custom K8s Resources

Create `k8s/` directory in your project:

```yaml
# k8s/my-service-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-service
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: my-service
  template:
    metadata:
      labels:
        app: my-service
    spec:
      containers:
      - name: my-service
        image: my-service:latest
        ports:
        - containerPort: 8080
```

Add task to deploy:

```yaml
# In your Taskfile.yml
tasks:
  k8s:deploy-my-service:
    desc: Deploy my custom service
    cmds:
      - kubectl apply -f k8s/my-service-deployment.yaml
```

### Add Custom Helm Charts

```bash
# Add to your Taskfile.yml
tasks:
  helm:deploy-redis:
    desc: Deploy Redis to cluster
    cmds:
      - helm repo add bitnami https://charts.bitnami.com/bitnami
      - helm repo update
      - helm upgrade --install redis bitnami/redis \
          --namespace redis --create-namespace \
          --wait
```

## Troubleshooting

### Tools Not Found After Install

```bash
# Reload shell environment
source ~/.bashrc  # Linux/WSL2
source ~/.zshrc   # macOS

# Or open new terminal
```

### Docker Permission Denied (WSL2)

```bash
# Add user to docker group
sudo usermod -aG docker $USER

# Restart WSL2 or run
newgrp docker
```

### Kind Cluster Won't Start

```bash
# Ensure Docker is running
docker info

# Delete and recreate cluster
task noetl:kind:local:cluster-delete
task noetl:kind:local:cluster-create
```

### Python Dependencies Conflict

```bash
# Recreate venv
rm -rf .venv
task bootstrap:venv

# Or use uv for faster resolution
pip install uv
uv pip install -e ./noetl -e .
```

### Port Conflicts

NoETL uses these ports:
- 8083: NoETL API/UI
- 5432: PostgreSQL (via port-forward)
- 3000: Grafana (via port-forward)

Check for conflicts:

```bash
# macOS
lsof -i :8083

# Linux
sudo netstat -tulpn | grep 8083
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: NoETL Integration Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: recursive
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      
      - name: Bootstrap NoETL
        run: |
          ./noetl/ci/bootstrap/bootstrap.sh --os linux
      
      - name: Run tests
        run: |
          source .venv/bin/activate
          pytest tests/
```

## Best Practices

1. **Version Pin NoETL Submodule**: Pin to specific tag/commit for stability
   ```bash
   cd noetl
   git checkout v1.0.4
   cd ..
   git add noetl
   git commit -m "Pin noetl to v1.0.4"
   ```

2. **Separate Credentials**: Keep credentials in separate directory, gitignored
   ```bash
   # In .gitignore
   credentials/
   *.local.json
   .env.local
   ```

3. **Use Task Aliases**: Create short aliases for common workflows
   ```yaml
   tasks:
     dev:
       desc: Start development environment
       aliases: [d]
       cmds:
         - task: noetl:dev:k8s:bootstrap
   ```

4. **Document Custom Setup**: Add `DEVELOPMENT.md` with project-specific instructions

5. **Test Bootstrap Regularly**: Verify bootstrap works on clean environment

## Support

- NoETL Issues: https://github.com/noetl/noetl/issues
- Documentation: https://noetl.io
- Examples: See `noetl/examples/` directory
