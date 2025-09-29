# NoETL Installation Guide

This guide provides detailed instructions for installing NoETL using different methods.

## Prerequisites

1. Python 3.11+ (3.12 recommended)
2. For full functionality:
   - PostgreSQL database (optional, for persistent storage)
   - Docker (optional, for containerized deployment)

## Installation Methods

### 1. PyPI Installation (Recommended)

The simplest way to install NoETL is via pip:

```bash
pip install noetl
```

For a specific version:

```bash
pip install noetl==0.1.18
```

It's recommended to install NoETL in a virtual environment:

```bash
# Create a virtual environment
python -m venv .venv

# Activate the virtual environment
# On Linux/macOS
source .venv/bin/activate
# On Windows
.venv\Scripts\activate

# Install NoETL
pip install noetl
```

### 2. Kubernetes Unified Platform (Recommended for Development)

For a complete development environment with integrated observability:

**Prerequisites:**
- Docker
- Kind (Kubernetes in Docker)
- kubectl
- Helm

**Quick Setup:**
```bash
# Clone repository
git clone https://github.com/noetl/noetl.git
cd noetl

# Deploy complete platform
make unified-deploy

# OR: Complete recreation from scratch
make unified-recreate-all

# Check health
make unified-health-check
```

**Services Available:**
- NoETL Server: http://localhost:30082
- Grafana: http://localhost:3000 (admin/admin)
- VictoriaMetrics: http://localhost:8428/vmui/
- VictoriaLogs: http://localhost:9428

**Management:**
```bash
# Port forwarding
make unified-port-forward-start
make unified-port-forward-status
make unified-port-forward-stop

# Get credentials
make unified-grafana-credentials

# View all commands
make help

# Clean up
kind delete cluster --name noetl-cluster
```

### 3. Local Development Installation

For development or contributing to NoETL:

1. Clone the repository:
   ```bash
   git clone https://github.com/noetl/noetl.git
   cd noetl
   ```

2. Install uv package manager:
   ```bash
   make install-uv
   ```

3. Create a Python virtual environment:
   ```bash
   make create-venv
   ```

4. Activate the virtual environment:
   ```bash
   source .venv/bin/activate
   ```

5. Install dependencies:
   ```bash
   make install
   ```

### 3. Kubernetes Unified Deployment (Recommended for Development)

For a complete development environment with server, workers, and observability:

**Prerequisites:**
- Docker
- Kind (Kubernetes in Docker)
- kubectl
- Helm (for observability stack)

**Quick Start:**
```bash
# Clone the repository
git clone https://github.com/noetl/noetl.git
cd noetl

# Deploy unified platform
./k8s/deploy-unified-platform.sh
```

**This provides:**
- NoETL server at http://localhost:30082
- Grafana dashboard at http://localhost:3000 (admin/admin)
- VictoriaMetrics at http://localhost:8428/vmui/
- All components in unified `noetl-platform` namespace
- Automatic monitoring and logging

**Clean up:**
```bash
kind delete cluster --name noetl-cluster
```

### 4. Docker Installation

NoETL can be run using Docker:

1. Pull the Docker image:
   ```bash
   docker pull noetl/noetl:latest
   ```

2. Run NoETL server in Docker:
   ```bash
   docker run -p 8082:8082 noetl/noetl:latest
   ```

Alternatively, you can build and run the Docker containers from source:

1. Build the Docker containers:
   ```bash
   make build
   ```

2. Start the Docker containers:
   ```bash
   make up
   ```

## Verifying Installation

After installation, verify that NoETL is installed correctly:

```bash
noetl --version
```

You should see the version number of NoETL.

## Next Steps

- [CLI Usage Guide](cli_usage.md) - Learn how to use the NoETL command-line interface
- [API Usage Guide](api_usage.md) - Learn how to use the NoETL REST API
- [Docker Usage Guide](docker_usage.md) - Learn how to use NoETL with Docker