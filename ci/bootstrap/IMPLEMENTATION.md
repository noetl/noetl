# NoETL Submodule Bootstrap - Implementation Summary

## Overview

Complete bootstrap infrastructure for projects that use NoETL as a git submodule. Supports both macOS and WSL2/Ubuntu with automated tool installation, Python environment setup, and full Kubernetes infrastructure deployment.

## Created Files

### 1. Bootstrap Script (`ci/bootstrap/bootstrap.sh`)
**Purpose**: Main automation script for complete environment setup

**Features**:
- Auto-detects OS (macOS or WSL2/Ubuntu)
- Installs system tools (Docker, kubectl, helm, jq, yq, psql, task, kind)
- Creates Python venv combining project + NoETL dependencies
- Sets up Kind Kubernetes cluster with full NoETL infrastructure
- Idempotent (can run multiple times safely)

**Usage**:
```bash
# Auto-detect OS
./noetl/ci/bootstrap/bootstrap.sh

# Specify OS
./noetl/ci/bootstrap/bootstrap.sh --os macos
./noetl/ci/bootstrap/bootstrap.sh --os linux

# Skip specific steps
./noetl/ci/bootstrap/bootstrap.sh --skip-tools
./noetl/ci/bootstrap/bootstrap.sh --skip-cluster

# Custom venv path
./noetl/ci/bootstrap/bootstrap.sh --venv-path ./venv
```

**Tool Installation**:

**macOS** (via Homebrew):
- kubectl, helm, jq, yq, task
- libpq (PostgreSQL client)
- docker, kind
- python@3.12

**Linux/WSL2** (via apt + curl):
- kubectl, helm, yq, task, kind
- postgresql-client
- build-essential, git, curl, jq
- python3, python3-venv, python3-pip

### 2. Project Taskfile Template (`ci/bootstrap/Taskfile-bootstrap.yml`)
**Purpose**: Complete Taskfile for projects using NoETL

**Key Features**:
- Imports all NoETL tasks with `noetl:` prefix
- Bootstrap verification and setup tasks
- Development workflow (start/stop/restart/status)
- Credential and playbook management
- Kubernetes helpers (logs, port-forwarding, shell access)
- Testing and cleanup tasks
- Documentation and quick reference

**Task Categories**:
```bash
# Bootstrap
task bootstrap                    # Complete setup
task bootstrap:verify            # Verify tools
task bootstrap:venv              # Create Python venv

# Development
task dev:setup                   # Full environment setup
task dev:start                   # Start infrastructure
task dev:stop                    # Stop infrastructure
task dev:status                  # Show status

# Credentials & Playbooks
task credentials:register        # Register credentials
task playbooks:register          # Register playbooks
task playbooks:list              # List playbooks
task playbooks:execute -- <name> # Execute playbook

# Kubernetes
task k8s:logs:noetl             # Server logs
task k8s:logs:worker            # Worker logs
task k8s:port-forward:ui        # Port-forward UI
task k8s:port-forward:postgres  # Port-forward Postgres
task k8s:port-forward:grafana   # Port-forward Grafana

# Cleanup
task clean:cache                # Clear cache
task clean:venv                 # Remove venv
task clean:cluster              # Delete cluster
task clean:all                  # Clean everything
```

### 3. Project pyproject.toml Template (`ci/bootstrap/pyproject-template.toml`)
**Purpose**: Python project configuration template

**Features**:
- Ready for editable NoETL installation from submodule
- Example dependencies for common use cases
- Optional dependency groups (dev, test, docs)
- pytest, coverage, black, ruff, mypy configuration
- Proper exclusion of NoETL submodule from project package

**Usage**:
```bash
# Copy to project root
cp noetl/ci/bootstrap/pyproject-template.toml ./pyproject.toml

# Edit project details
# [project]
# name = "my-project"
# ...

# Install (bootstrap script does this automatically)
python3 -m venv .venv
source .venv/bin/activate
pip install uv
uv pip install -e ./noetl  # NoETL from submodule
uv pip install -e .         # Your project
uv pip install -e ".[dev]" # With dev dependencies
```

### 4. Gitignore Template (`ci/bootstrap/gitignore-template`)
**Purpose**: Comprehensive .gitignore for projects

**Excludes**:
- Python artifacts (__pycache__, *.pyc, .venv)
- IDE files (.idea, .vscode, .DS_Store)
- **Credentials** (credentials/, *.secret.json, .env.local)
- Data directories (data/, *.db, logs/)
- NoETL cache (noetl/ci/kind/cache/, noetl/data/)

**Includes**:
- Template files (*.example.json, *.template.json)

### 5. Documentation

**README.md** (`ci/bootstrap/README.md`):
- Complete overview of bootstrap system
- Architecture and directory structure
- Task reference
- Development workflow guide
- Extension patterns (custom K8s resources, Helm charts)
- Troubleshooting guide
- CI/CD integration examples
- Best practices

**QUICKSTART.md** (`ci/bootstrap/QUICKSTART.md`):
- Step-by-step quick start guide
- Project creation from scratch
- First playbook tutorial
- Service access instructions
- Common tasks reference
- Credential and playbook examples
- Testing examples
- Updating submodule instructions

## Architecture

### Directory Structure

```
project-using-noetl/
├── .git/                           # Project git repository
├── .gitignore                      # Project-specific ignores
├── .venv/                          # Python venv (project + noetl)
├── Taskfile.yml                    # Project taskfile (imports noetl tasks)
├── pyproject.toml                  # Project dependencies
├── README.md                       # Project documentation
│
├── playbooks/                      # Custom playbooks
│   ├── workflow1.yaml
│   └── workflow2.yaml
│
├── credentials/                    # Credentials (gitignored!)
│   ├── service1.json
│   └── service2.json.example       # Templates (tracked in git)
│
├── tests/                          # Project tests
│   ├── test_playbooks.py
│   └── test_integration.py
│
└── noetl/                          # NoETL submodule (read-only)
    ├── ci/
    │   ├── bootstrap/              # ⭐ Bootstrap infrastructure
    │   │   ├── bootstrap.sh        # Main bootstrap script
    │   │   ├── Taskfile-bootstrap.yml
    │   │   ├── pyproject-template.toml
    │   │   ├── gitignore-template
    │   │   ├── README.md
    │   │   └── QUICKSTART.md
    │   ├── taskfile/               # NoETL taskfiles
    │   │   ├── kind.yml
    │   │   ├── postgres.yml
    │   │   ├── noetl.yml
    │   │   ├── vmstack.yml
    │   │   ├── docker.yml
    │   │   ├── tools.yml
    │   │   ├── test.yml
    │   │   └── tshoot.yml
    │   ├── kind/                   # Kind cluster config
    │   │   ├── config.yaml
    │   │   └── cache/              # Local cache (gitignored)
    │   ├── manifests/              # K8s manifests
    │   │   ├── postgres/
    │   │   └── noetl/
    │   └── vmstack/                # Monitoring configs
    │       ├── vmstack-values.yaml
    │       └── vmlogs-values.yaml
    ├── noetl/                      # NoETL Python package
    └── taskfile.yml                # NoETL main taskfile
```

### Bootstrap Flow

```
1. bootstrap.sh
   ├── Detect OS (macOS or WSL2/Ubuntu)
   ├── Install system tools
   │   ├── macOS: Homebrew + brew install <tools>
   │   └── Linux: apt + curl downloads
   ├── Verify tools installation
   ├── Setup Python venv
   │   ├── Create .venv
   │   ├── Install uv (fast package installer)
   │   ├── Install NoETL: uv pip install -e ./noetl
   │   └── Install project: uv pip install -e .
   ├── Create project Taskfile.yml (if missing)
   └── Setup NoETL infrastructure
       ├── Create Kind cluster
       ├── Deploy PostgreSQL
       ├── Deploy VictoriaMetrics monitoring
       └── Deploy NoETL server + workers

2. Task System
   ├── Project Taskfile.yml (imported from template)
   │   ├── Bootstrap tasks
   │   ├── Development workflow tasks
   │   └── Includes noetl: taskfile
   └── NoETL taskfile.yml
       ├── Includes all ci/taskfile/*.yml
       └── Provides infrastructure tasks
```

### Python Environment

The bootstrap creates a unified venv containing:
1. **NoETL** (installed from `./noetl` submodule in editable mode)
2. **Project dependencies** (from project's `pyproject.toml`)
3. **All NoETL dependencies** (postgres, duckdb, snowflake drivers, etc.)

This allows:
- Projects to import `noetl` modules
- Access to `noetl` CLI command
- Shared dependency resolution
- Single activation: `source .venv/bin/activate`

### Task Inheritance

Projects inherit all NoETL tasks via includes:

```yaml
# Project Taskfile.yml
includes:
  noetl:
    taskfile: ./noetl/taskfile.yml
    dir: ./noetl

# Now available:
# task noetl:kind:local:cluster-create
# task noetl:postgres:k8s:deploy
# task noetl:monitoring:k8s:deploy
# etc.
```

Task aliases in project Taskfile can simplify:
```yaml
tasks:
  start:
    aliases: [up]
    cmds:
      - task: noetl:dev:k8s:bootstrap
```

## OS-Specific Implementation

### macOS

**Package Manager**: Homebrew
- Auto-installs Homebrew if missing
- Handles Apple Silicon PATH (`/opt/homebrew/bin/brew`)
- Uses `brew install` for all tools
- Requires Docker Desktop (manual install)

**Special Cases**:
- PostgreSQL client: `brew install libpq` + `brew link --force libpq`
- Python: `brew install python@3.12`
- Checks Docker Desktop running via `pgrep -x "Docker"`

### WSL2/Ubuntu

**Package Managers**: apt + curl downloads
- Uses `apt-get` for system packages
- Uses curl for kubectl, helm, yq, kind binary downloads
- Installs to `/usr/local/bin` (requires sudo)

**Special Cases**:
- Docker: Must use Docker Desktop for Windows with WSL2 backend
- Docker permissions: Adds user to docker group
- yq: Uses mikefarah/yq (Go version) not Python yq
- Detects WSL2: `grep -qi microsoft /proc/version`

## Integration Patterns

### Adding Custom Infrastructure

Projects can extend NoETL infrastructure:

```yaml
# In project Taskfile.yml
tasks:
  k8s:deploy-redis:
    desc: Deploy Redis to cluster
    cmds:
      - helm repo add bitnami https://charts.bitnami.com/bitnami
      - helm upgrade --install redis bitnami/redis \
          --namespace redis --create-namespace \
          --wait
  
  dev:setup-extended:
    desc: Setup NoETL + custom services
    cmds:
      - task: noetl:dev:k8s:bootstrap
      - task: k8s:deploy-redis
```

### CI/CD Integration

```yaml
# .github/workflows/test.yml
name: Integration Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: recursive
      
      - name: Bootstrap
        run: ./noetl/ci/bootstrap/bootstrap.sh --os linux
      
      - name: Run tests
        run: |
          source .venv/bin/activate
          pytest tests/
```

### Version Pinning

```bash
# Pin NoETL to specific version
cd noetl
git checkout v1.0.4
cd ..
git add noetl
git commit -m "Pin noetl to v1.0.4"
```

## Security Considerations

### Credentials Management

**Bootstrap implements**:
- Gitignore credentials/ directory by default
- Example/template files tracked in git (*.example.json)
- Actual credentials never committed

**Best practices enforced**:
```gitignore
# Credentials (NEVER commit!)
credentials/
secrets/
*.secret.json
*.local.json
.env.local

# Keep templates
!credentials/*.example.json
!credentials/*.template.json
```

### Kubernetes Secrets

Projects should use K8s secrets for production:
```bash
kubectl create secret generic my-secret \
  --from-file=credentials.json=credentials/my_service.json \
  -n noetl
```

## Testing

Bootstrap script is testable:

```bash
# Test on clean environment
docker run -it --rm ubuntu:22.04 bash
# Inside container:
apt-get update && apt-get install -y git
git clone <project-repo>
cd <project-repo>
git submodule update --init --recursive
./noetl/ci/bootstrap/bootstrap.sh --os linux
```

Project tests can use NoETL infrastructure:

```python
# tests/test_integration.py
import requests

def test_noetl_api_available():
    response = requests.get("http://localhost:8083/api/health")
    assert response.status_code == 200
```

## Maintenance

### Updating Bootstrap

When updating bootstrap infrastructure in NoETL:
1. Test changes in clean environment
2. Update version in commit message
3. Document breaking changes in CHANGELOG.md
4. Projects pull updates via `git submodule update`

### Breaking Changes

If bootstrap has breaking changes:
1. Increment major version tag (v2.0.0)
2. Document migration guide
3. Allow projects to pin to v1.x.x if needed

## Performance

### Bootstrap Timing

- **Tool installation**: 2-5 minutes (first time)
- **Python venv setup**: 1-2 minutes
- **Kind cluster + infrastructure**: 5-10 minutes
- **Total first run**: ~10-15 minutes
- **Subsequent runs**: <1 minute (skips installed tools)

### Optimization

Bootstrap uses:
- `uv` for faster Python package installation (5-10x faster than pip)
- Parallel tool downloads where possible
- Cached Docker images in Kind
- Idempotent operations (safe to re-run)

## Troubleshooting Reference

Common issues and solutions built into bootstrap:

1. **Docker not accessible (WSL2)**
   - Auto-adds user to docker group
   - Prompts for newgrp/re-login

2. **Tools not in PATH**
   - Bootstrap adds PATH exports to ~/.bashrc or ~/.zprofile
   - Prompts user to reload shell

3. **Port conflicts**
   - Lists ports used (8083, 5432, 3000)
   - Provides check commands

4. **Python version mismatch**
   - Validates Python 3.12+
   - Clear error message if wrong version

## Future Enhancements

Potential improvements:
- [ ] Support for Windows native (not WSL2)
- [ ] Alternative to Kind (k3s, minikube)
- [ ] Optional components (skip monitoring, use external Postgres)
- [ ] Multi-project isolation (separate clusters)
- [ ] Bootstrap verification tests
- [ ] Auto-update mechanism for submodule

## Summary

The bootstrap infrastructure provides:

✅ **Complete automation**: Single command setup
✅ **Cross-platform**: macOS and WSL2/Ubuntu
✅ **Production-ready**: Full observability stack
✅ **Developer-friendly**: Task automation and clear docs
✅ **Extensible**: Easy to add custom infrastructure
✅ **Secure**: Credentials management built-in
✅ **Well-documented**: README, QUICKSTART, inline comments
✅ **Tested patterns**: Based on NoETL's own development workflow

Projects get NoETL's full local development infrastructure with minimal setup, allowing them to focus on building data workflows rather than infrastructure management.
