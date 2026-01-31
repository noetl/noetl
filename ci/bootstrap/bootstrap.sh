#!/usr/bin/env bash
#
# NoETL Bootstrap Script for Projects Using NoETL as Submodule
#
# This script MUST be run first to install all required tools.
# It sets up a complete development environment including:
# - System tools (Docker, kubectl, helm, kind, psql, pyenv, uv)
# - Python virtual environment (project + noetl dependencies)
# - Kind Kubernetes cluster with NoETL infrastructure
# - Project template files (.env.local, pyproject.toml, .gitignore)
# - Project directories (credentials/, playbooks/, data/, logs/, secrets/)
#
# Quick Start (from your project root):
#   git submodule update --init --recursive
#   ./.noetl/ci/bootstrap/bootstrap.sh
#
# After bootstrap completes, you can use 'noetl run' commands.
# Usage:
#   ./bootstrap.sh [OPTIONS]
#
# Options:
#   --os {macos|linux}     Operating system (auto-detected if not specified)
#   --skip-tools           Skip system tool installation
#   --skip-venv            Skip Python venv setup
#   --skip-cluster         Skip Kind cluster creation
#   --venv-path PATH       Custom venv path (default: .venv)
#   --help                 Show this help message

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOETL_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROJECT_ROOT="$(cd "$NOETL_ROOT/.." && pwd)"
VENV_PATH="$PROJECT_ROOT/.venv"

# Default options
SKIP_TOOLS=false
SKIP_VENV=false
SKIP_CLUSTER=false
OS_TYPE=""

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Help message
show_help() {
    cat << EOF
NoETL Bootstrap Script

Sets up complete development environment for projects using NoETL as submodule.

Usage:
  $0 [OPTIONS]

Options:
  --os {macos|linux}     Operating system (auto-detected if not specified)
  --skip-tools           Skip system tool installation
  --skip-venv            Skip Python venv setup
  --skip-cluster         Skip Kind cluster creation
  --venv-path PATH       Custom venv path (default: .venv)
  --help                 Show this help message

Examples:
  # Full bootstrap (auto-detect OS)
  $0

  # macOS with custom venv path
  $0 --os macos --venv-path ./venv

  # Skip cluster creation
  $0 --skip-cluster

EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --os)
            OS_TYPE="$2"
            shift 2
            ;;
        --skip-tools)
            SKIP_TOOLS=true
            shift
            ;;
        --skip-venv)
            SKIP_VENV=true
            shift
            ;;
        --skip-cluster)
            SKIP_CLUSTER=true
            shift
            ;;
        --venv-path)
            VENV_PATH="$2"
            shift 2
            ;;
        --help)
            show_help
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Detect OS if not specified
detect_os() {
    if [[ -n "$OS_TYPE" ]]; then
        return
    fi

    if [[ "$OSTYPE" == "darwin"* ]]; then
        OS_TYPE="macos"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if grep -qi microsoft /proc/version 2>/dev/null; then
            OS_TYPE="linux"
            log_info "Detected WSL2/Ubuntu"
        else
            OS_TYPE="linux"
            log_info "Detected Linux"
        fi
    else
        log_error "Unsupported OS: $OSTYPE"
        exit 1
    fi

    log_info "Auto-detected OS: $OS_TYPE"
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Install Homebrew (macOS)
install_homebrew() {
    if ! command_exists brew; then
        log_info "Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

        # Add to PATH for Apple Silicon
        if [[ -f "/opt/homebrew/bin/brew" ]]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
            echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
        fi

        log_success "Homebrew installed"
    else
        log_info "Homebrew already installed: $(brew --version | head -n1)"
    fi
}

# Install tools on macOS
install_tools_macos() {
    log_info "Installing tools on macOS..."

    install_homebrew

    # Update Homebrew
    brew update

    # Install tools
    local tools=(
        "kubectl"
        "helm"
        "jq"
        "yq"
        "libpq"  # PostgreSQL client
        "docker"
        "kind"
        "python@3.12"
        "pyenv"
    )

    for tool in "${tools[@]}"; do
        local cmd="${tool##*/}"  # Extract command name
        cmd="${cmd%@*}"          # Remove version suffix

        if command_exists "$cmd"; then
            log_info "$cmd already installed"
        else
            log_info "Installing $tool..."
            brew install "$tool"
        fi
    done

    # Link PostgreSQL client tools
    if ! command_exists psql; then
        log_info "Linking PostgreSQL client tools..."
        brew link --force libpq
    fi

    # Install uv (Python package manager)
    if ! command_exists uv; then
        log_info "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.cargo/bin:$PATH"
    fi

    # Check Docker installation and status
    if ! command_exists docker; then
        log_warning "Docker CLI not found. Installing docker..."
        brew install docker
    fi

    # Verify Docker Desktop is running
    if ! docker info >/dev/null 2>&1; then
        if ! pgrep -x "Docker" > /dev/null; then
            log_warning "Docker Desktop not running."
            log_info "Attempting to start Docker Desktop..."
            open -a Docker
            log_info "Waiting for Docker to start (this may take 30-60 seconds)..."

            # Wait for Docker to be ready (max 2 minutes)
            local timeout=120
            local elapsed=0
            while ! docker info >/dev/null 2>&1; do
                if [[ $elapsed -ge $timeout ]]; then
                    log_error "Docker failed to start within $timeout seconds"
                    log_info "Please start Docker Desktop manually and re-run this script"
                    exit 1
                fi
                sleep 5
                elapsed=$((elapsed + 5))
                echo -n "."
            done
            echo ""
            log_success "Docker Desktop started successfully"
        else
            log_error "Docker Desktop is running but docker command is not working"
            log_info "Please check Docker Desktop settings and ensure it's fully initialized"
            exit 1
        fi
    else
        log_success "Docker is running: $(docker --version)"
    fi

    log_success "macOS tools installed"
}

# Install tools on Linux/WSL2
install_tools_linux() {
    log_info "Installing tools on Linux/WSL2..."

    # Update package lists
    sudo apt-get update

    # Install base tools
    sudo apt-get install -y \
        git make curl jq ca-certificates lsof \
        build-essential unzip \
        python3 python3-venv python3-pip \
        postgresql-client

    # Install kubectl
    if ! command_exists kubectl; then
        log_info "Installing kubectl..."
        curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
        sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
        rm kubectl
    fi

    # Install helm
    if ! command_exists helm; then
        log_info "Installing helm..."
        curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
    fi

    # Install yq (mikefarah/yq)
    if ! command_exists yq || ! yq --version 2>&1 | grep -q "mikefarah"; then
        log_info "Installing yq (mikefarah/yq)..."
        YQ_VERSION=$(curl -s https://api.github.com/repos/mikefarah/yq/releases/latest | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/')
        sudo wget -qO /usr/local/bin/yq "https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/yq_linux_amd64"
        sudo chmod +x /usr/local/bin/yq
    fi

    # Install pyenv
    if ! command_exists pyenv; then
        log_info "Installing pyenv..."
        curl https://pyenv.run | bash

        # Add to shell profile if not already present
        if ! grep -q 'pyenv init' ~/.bashrc 2>/dev/null; then
            echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
            echo 'export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
            echo 'eval "$(pyenv init -)"' >> ~/.bashrc
        fi

        export PYENV_ROOT="$HOME/.pyenv"
        export PATH="$PYENV_ROOT/bin:$PATH"
        eval "$(pyenv init -)" 2>/dev/null || true
    fi

    # Install tfenv
    if ! command_exists tfenv; then
        log_info "Installing tfenv..."
        git clone --depth=1 https://github.com/tfutils/tfenv.git ~/.tfenv

        # Add to PATH if not already present
        if ! grep -q '.tfenv/bin' ~/.bashrc 2>/dev/null; then
            echo 'export PATH="$HOME/.tfenv/bin:$PATH"' >> ~/.bashrc
        fi

        export PATH="$HOME/.tfenv/bin:$PATH"
    fi

    # Install uv (Python package manager)
    if ! command_exists uv; then
        log_info "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.cargo/bin:$PATH"
    fi

    # Install kind
    if ! command_exists kind; then
        log_info "Installing kind..."
        curl -Lo ./kind https://kind.sigs.k8s.io/dl/latest/kind-linux-amd64
        sudo install -o root -g root -m 0755 kind /usr/local/bin/kind
        rm kind
    fi

    # Check Docker
    if ! command_exists docker; then
        log_warning "Docker not found. Installing Docker..."

        # Add Docker's official GPG key
        sudo apt-get update
        sudo apt-get install -y ca-certificates curl
        sudo install -m 0755 -d /etc/apt/keyrings
        sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
        sudo chmod a+r /etc/apt/keyrings/docker.asc

        # Add Docker repository
        echo \
          "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
          $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
          sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

        # Install Docker Engine
        sudo apt-get update
        sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

        log_success "Docker installed successfully"
    fi

    if ! docker info >/dev/null 2>&1; then
        log_warning "Docker daemon not accessible. Fixing permissions..."
        sudo groupadd -f docker
        sudo usermod -aG docker "$USER"
        log_warning "Docker group added. Please run: newgrp docker"
        log_info "Or log out and log back in for changes to take effect"

        # Try starting docker if it's not running
        if ! sudo systemctl is-active --quiet docker; then
            log_info "Starting Docker service..."
            sudo systemctl start docker
            sudo systemctl enable docker
        fi

        # Check again after starting
        if ! docker info >/dev/null 2>&1; then
            log_error "Docker still not accessible. Please run: newgrp docker"
            log_info "Then re-run this script"
            exit 1
        fi
    fi

    log_success "Linux tools installed"
}

# Verify tools installation
verify_tools() {
    log_info "Verifying tools installation..."

    local required_tools=(
        "docker"
        "kubectl"
        "helm"
        "kind"
        "jq"
        "yq"
        "psql"
        "python3"
        "pyenv"
        "uv"
    )

    local missing_tools=()

    for tool in "${required_tools[@]}"; do
        if command_exists "$tool"; then
            log_success "$tool: $(command -v $tool)"
        else
            log_error "$tool: NOT FOUND"
            missing_tools+=("$tool")
        fi
    done

    if [[ ${#missing_tools[@]} -gt 0 ]]; then
        log_error "Missing tools: ${missing_tools[*]}"
        return 1
    fi

    # Check Docker daemon
    if ! docker info >/dev/null 2>&1; then
        log_error "Docker daemon not accessible"
        return 1
    fi

    log_success "All tools verified"
}

# Setup Python virtual environment
setup_venv() {
    log_info "Setting up Python virtual environment at: $VENV_PATH"

    # Check Python version
    if ! command_exists python3; then
        log_error "python3 not found"
        exit 1
    fi

    local python_version=$(python3 --version | awk '{print $2}')
    log_info "Python version: $python_version"

    # Require Python 3.12+
    local major=$(echo "$python_version" | cut -d. -f1)
    local minor=$(echo "$python_version" | cut -d. -f2)

    if [[ "$major" -lt 3 ]] || [[ "$major" -eq 3 && "$minor" -lt 12 ]]; then
        log_error "Python 3.12+ required, found $python_version"
        exit 1
    fi

    # Create venv if it doesn't exist
    if [[ ! -d "$VENV_PATH" ]]; then
        log_info "Creating virtual environment..."
        python3 -m venv "$VENV_PATH"
        log_success "Virtual environment created"
    else
        log_info "Virtual environment already exists"
    fi

    # Activate venv
    source "$VENV_PATH/bin/activate"

    # Upgrade pip
    log_info "Upgrading pip..."
    pip install --upgrade pip

    # Install uv for faster package installation
    log_info "Installing uv..."
    pip install uv

    # Install noetl in development mode with CLI
    log_info "Installing NoETL with CLI..."
    cd "$NOETL_ROOT"
    uv pip install -e ".[cli]"

    # Install project dependencies if pyproject.toml exists
    if [[ -f "$PROJECT_ROOT/pyproject.toml" ]]; then
        log_info "Installing project dependencies..."
        cd "$PROJECT_ROOT"
        uv pip install -e .
    else
        log_warning "No pyproject.toml found in project root. Skipping project dependencies."
    fi

    # Verify noetl installation
    if command_exists noetl; then
        log_success "NoETL installed: $(noetl --version 2>&1 || echo 'CLI available')"
    else
        log_error "NoETL CLI not available after installation"
        exit 1
    fi

    log_success "Python environment setup complete"
    log_info "To activate: source $VENV_PATH/bin/activate"
}

# Setup NoETL infrastructure
setup_cluster() {
    log_info "Setting up NoETL infrastructure..."

    # Ensure we're in noetl directory
    cd "$NOETL_ROOT"

    # Check if cluster already exists
    if kind get clusters 2>/dev/null | grep -q "^noetl$"; then
        log_info "Kind cluster 'noetl' already exists"
        read -p "Delete and recreate? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log_info "Deleting existing cluster..."
            kind delete cluster --name noetl || true
        else
            log_info "Using existing cluster"
            return 0
        fi
    fi

    # Run full bootstrap using noetl playbook
    log_info "Running NoETL bootstrap (this may take several minutes)..."
    noetl run automation/boot.yaml

    log_success "NoETL infrastructure ready"
    log_info "NoETL Server API: http://localhost:8082"
    log_info "Gateway API: http://localhost:8090"
    log_info "Gateway UI: http://localhost:8080"
    echo ""
    log_info "Observability Services:"
    log_info "  - ClickHouse HTTP:    http://localhost:30123"
    log_info "  - ClickHouse Native:  localhost:30900"
    log_info "  - Qdrant HTTP:        http://localhost:30633"
    log_info "  - Qdrant gRPC:        localhost:30634"
    log_info "  - NATS Client:        nats://localhost:30422"
    log_info "  - NATS Monitoring:    http://localhost:30822"
    echo ""
    log_info "Monitoring:"
    log_info "  - Grafana: kubectl port-forward -n vmstack svc/vmstack-grafana 3000:80"
    log_info "    (includes ClickHouse datasource for querying observability data)"
    log_info "  - Postgres: kubectl port-forward -n postgres svc/postgres 5432:5432"
}

# Copy template files to project root
copy_templates() {
    log_info "Copying template files to project root..."

    # Copy .env.local template if it doesn't exist
    if [[ ! -f "$PROJECT_ROOT/.env.local" ]]; then
        if [[ -f "$NOETL_ROOT/ci/bootstrap/env-template" ]]; then
            cp "$NOETL_ROOT/ci/bootstrap/env-template" "$PROJECT_ROOT/.env.local"
            log_success "Created .env.local from template"
            log_info "Edit .env.local to customize your environment configuration"
        else
            log_warning "env-template not found in $NOETL_ROOT/ci/bootstrap/"
        fi
    else
        log_info ".env.local already exists, skipping"
    fi

    # Copy .gitignore template if it doesn't exist
    if [[ ! -f "$PROJECT_ROOT/.gitignore" ]]; then
        if [[ -f "$NOETL_ROOT/ci/bootstrap/gitignore-template" ]]; then
            cp "$NOETL_ROOT/ci/bootstrap/gitignore-template" "$PROJECT_ROOT/.gitignore"
            log_success "Created .gitignore from template"
        else
            log_warning "gitignore-template not found in $NOETL_ROOT/ci/bootstrap/"
        fi
    else
        log_info ".gitignore already exists, skipping"
    fi

    # Copy pyproject.toml template if it doesn't exist
    if [[ ! -f "$PROJECT_ROOT/pyproject.toml" ]]; then
        if [[ -f "$NOETL_ROOT/ci/bootstrap/pyproject-template.toml" ]]; then
            cp "$NOETL_ROOT/ci/bootstrap/pyproject-template.toml" "$PROJECT_ROOT/pyproject.toml"
            log_success "Created pyproject.toml from template"
            log_info "Edit pyproject.toml to add your project dependencies"
        else
            log_warning "pyproject-template.toml not found in $NOETL_ROOT/ci/bootstrap/"
        fi
    else
        log_info "pyproject.toml already exists, skipping"
    fi

    # Create essential directories
    local dirs=("credentials" "playbooks" "data" "logs" "secrets")
    for dir in "${dirs[@]}"; do
        if [[ ! -d "$PROJECT_ROOT/$dir" ]]; then
            mkdir -p "$PROJECT_ROOT/$dir"
            log_success "Created $dir/ directory"
        fi
    done

    # Create README in credentials directory
    if [[ ! -f "$PROJECT_ROOT/credentials/README.md" ]]; then
        cat > "$PROJECT_ROOT/credentials/README.md" << 'CREDEOF'
# Credentials

This directory contains credential YAML files for NoETL workflows.

## Format

```yaml
key: my_credential_name
type: postgres  # or: http, snowflake, gcs, etc.
username: myuser
password: mypassword
# Additional fields depending on credential type
```

## Security

- **NEVER** commit credential files to git
- This directory is excluded in .gitignore
- Use environment-specific credentials for dev/staging/prod

## Registration

Register credentials with NoETL server:

```bash
# Using NoETL CLI
noetl register credential --directory credentials/

# Or register a single credential
noetl register credential credentials/my_cred.yaml
```

See NoETL documentation for credential types and required fields.
CREDEOF
        log_success "Created credentials/README.md"
    fi

    log_success "Template files copied successfully"
}

# Main bootstrap flow
main() {
    echo ""
    echo "========================================"
    echo "  NoETL Bootstrap for Submodule Projects"
    echo "========================================"
    echo ""

    log_info "Project root: $PROJECT_ROOT"
    log_info "NoETL root: $NOETL_ROOT"
    log_info "Venv path: $VENV_PATH"
    echo ""

    # Detect OS
    detect_os
    echo ""

    # Install system tools
    if [[ "$SKIP_TOOLS" == false ]]; then
        log_info "=== Installing System Tools ==="
        if [[ "$OS_TYPE" == "macos" ]]; then
            install_tools_macos
        else
            install_tools_linux
        fi
        verify_tools
        echo ""
    else
        log_info "=== Skipping Tool Installation ==="
        verify_tools || log_warning "Some tools may be missing"
        echo ""
    fi

    # Setup Python venv
    if [[ "$SKIP_VENV" == false ]]; then
        log_info "=== Setting Up Python Environment ==="
        setup_venv
        echo ""
    else
        log_info "=== Skipping Python Venv Setup ==="
        echo ""
    fi

    # Copy template files
    log_info "=== Copying Template Files ==="
    copy_templates
    echo ""

    # Setup infrastructure
    if [[ "$SKIP_CLUSTER" == false ]]; then
        log_info "=== Setting Up NoETL Infrastructure ==="
        setup_cluster
        echo ""
    else
        log_info "=== Skipping Cluster Setup ==="
        echo ""
    fi

    # Final summary
    echo ""
    echo "========================================"
    echo "  Bootstrap Complete!"
    echo "========================================"
    echo ""
    log_success "NoETL development environment is ready"
    echo ""
    echo "Services:"
    echo "  - NoETL Server API:   http://localhost:8082"
    echo "  - Gateway API:        http://localhost:8090"
    echo "  - Gateway UI:         http://localhost:8080"
    echo "  - ClickHouse HTTP:    http://localhost:30123"
    echo "  - Qdrant HTTP:        http://localhost:30633"
    echo "  - NATS Monitoring:    http://localhost:30822"
    echo ""
    echo "Quick Start:"
    echo "  1. Activate venv:        source $VENV_PATH/bin/activate"
    echo "  2. Register credentials: noetl register credential --directory credentials/"
    echo "  3. Register playbooks:   noetl register playbook --directory playbooks/"
    echo "  4. View server logs:     kubectl logs -n noetl -l app=noetl-server -f"
    echo ""
    echo "Common Playbook Commands:"
    echo "  noetl run automation/boot.yaml                    # Full bootstrap"
    echo "  noetl run automation/destroy.yaml                 # Destroy cluster"
    echo "  noetl run automation/infrastructure/gateway.yaml --set action=status"
    echo ""
    echo "Execute Playbooks:"
    echo "  noetl execute playbook <name> --host localhost --port 8082"
    echo ""
    echo "Documentation:"
    echo "  - CI Setup: documentation/docs/operations/ci-setup.md"
    echo "  - Observability: documentation/docs/operations/observability.md"
    echo "  - Bootstrap guide: ci/bootstrap/README.md"
    echo ""
}

# Run main
main "$@"
