# NoETL Bootstrap for Submodule Projects

This directory contains bootstrap scripts for projects that use NoETL as a git submodule.

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

**The bootstrap script must be run first** - it installs all required tools including Docker, kubectl, and other dependencies.

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

### 3. Configure Environment

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

### 4. Verify Setup

```bash
# Activate virtual environment
source .venv/bin/activate

# Check NoETL CLI
noetl --help

# Verify infrastructure
kubectl get pods -A
```

## Files Created by Bootstrap

The bootstrap script creates the following files in your project root:

- `.env.local` - Environment configuration (from `env-template`)
- `.gitignore` - Git ignore rules (from `gitignore-template`)
- `pyproject.toml` - Python project config (from `pyproject-template.toml`)
- `credentials/` - Directory for credential files (with README)
- `playbooks/` - Directory for your playbooks
- `data/` - Directory for data files
- `logs/` - Directory for log files
- `secrets/` - Directory for secret files

All template files are located in `noetl/ci/bootstrap/` for reference.

## Directory Structure

```
your-project/
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
    │   ├── kind/                   # Kind cluster config
    │   ├── manifests/              # K8s manifests
    │   └── vmstack/                # Monitoring configs
    ├── noetl/                      # NoETL Python package
    └── automation/                 # NoETL playbooks for infrastructure
```

## Using NoETL Playbooks

NoETL provides automation playbooks for infrastructure management:

```bash
# Bootstrap full environment
noetl run automation/setup/bootstrap.yaml

# Manage Kind cluster
noetl run automation/infrastructure/kind.yaml --set action=create
noetl run automation/infrastructure/kind.yaml --set action=delete

# Deploy PostgreSQL
noetl run automation/infrastructure/postgres.yaml --set action=deploy

# Deploy NoETL services
noetl run automation/deployment/noetl-stack.yaml --set action=deploy

# Redeploy after code changes
noetl run automation/development/noetl.yaml --set action=redeploy

# Build Docker image
noetl run automation/development/docker.yaml --set action=build
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
- kubectl, helm, kind, jq, yq, postgresql-client

**Note:** If Docker Desktop is not installed, the script will install it via Homebrew and attempt to start it automatically.

### WSL2/Ubuntu

Required tools (bootstrap installs automatically):
- **Docker Engine** (auto-installed via apt if not present)
- **pyenv** (Python version manager via pyenv.run)
- **tfenv** (Terraform version manager via git)
- **uv** (Fast Python package manager via curl)
- Python 3.12+
- kubectl, helm, kind, jq, yq, postgresql-client
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

## Development Workflow

### 1. Start Infrastructure

```bash
# Full setup (first time)
noetl run automation/setup/bootstrap.yaml

# Or incremental
noetl run automation/infrastructure/kind.yaml --set action=create
noetl run automation/infrastructure/postgres.yaml --set action=deploy
noetl run automation/deployment/noetl-stack.yaml --set action=deploy
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
noetl register credentials/my_service.json \
  --host localhost --port 8083
```

### 3. Register Playbooks

```bash
# Register from your project
noetl register playbooks/my_workflow.yaml \
  --host localhost --port 8083

# Execute
noetl execute playbook my_workflow \
  --host localhost --port 8083
```

### 4. Access Services

```bash
# NoETL UI
open http://localhost:8083

# Grafana (monitoring)
noetl run automation/infrastructure/monitoring.yaml --set action=port-forward
open http://localhost:3000

# PostgreSQL
noetl run automation/infrastructure/postgres.yaml --set action=port-forward
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

Deploy with kubectl:

```bash
kubectl apply -f k8s/my-service-deployment.yaml
```

### Add Custom Helm Charts

```bash
# Deploy Redis
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update
helm upgrade --install redis bitnami/redis \
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
noetl run automation/infrastructure/kind.yaml --set action=delete
noetl run automation/infrastructure/kind.yaml --set action=create
```

### Python Dependencies Conflict

```bash
# Recreate venv
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install -e ./noetl -e .

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

3. **Document Custom Setup**: Add `DEVELOPMENT.md` with project-specific instructions

4. **Test Bootstrap Regularly**: Verify bootstrap works on clean environment

## Support

- NoETL Issues: https://github.com/noetl/noetl/issues
- Documentation: https://noetl.io
- Examples: See `noetl/examples/` directory
