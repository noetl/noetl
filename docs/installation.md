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

### 2. Local Development Installation

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

### 3. Docker Installation

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