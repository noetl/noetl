# NoETL Development Guide

This guide provides information about setting up a development environment for NoETL and contributing to the project.

## Prerequisites

- Python 3.11+ (3.12 recommended)
- Git
- Make (optional, for using the Makefile)
- Docker (optional, for containerized development)

## Setting Up a Development Environment

### Option 1: Unified Kubernetes Platform (Recommended)

For a complete development environment with integrated observability:

**Prerequisites:**
- Docker
- Kind (Kubernetes in Docker) 
- kubectl
- Helm

```bash
# Clone repository
git clone https://github.com/noetl/noetl.git
cd noetl

# Deploy complete platform
make unified-deploy

# OR: Complete recreation from scratch
make unified-recreate-all

# Check platform health
make unified-health-check

# View all available commands
make help
```

**Services Available:**
- NoETL Server: http://localhost:30082 (API & UI)
- Grafana: http://localhost:3000 (admin/admin)
- VictoriaMetrics: http://localhost:8428/vmui/
- VictoriaLogs: http://localhost:9428

**Management Commands:**
```bash
# Port forwarding
make unified-port-forward-start
make unified-port-forward-status
make unified-port-forward-stop

# Get credentials
make unified-grafana-credentials

# Clean up
kind delete cluster --name noetl-cluster
```

### Option 2: Local Python Development

#### 1. Clone the Repository

```bash
git clone https://github.com/noetl/noetl.git
cd noetl
```

#### 2. Create a Virtual Environment

#### Using Make

```bash
# Install uv package manager
make install-uv

# Create a virtual environment
make create-venv

# Activate the virtual environment
source .venv/bin/activate
```

#### Manually

```bash
# Create a virtual environment
python -m venv .venv

# Activate the virtual environment
# On Linux/macOS
source .venv/bin/activate
# On Windows
.venv\Scripts\activate

# Install uv package manager
pip install uv

# Install dependencies
uv pip install -e ".[dev]"
```

#### 3. Install Dependencies

```bash
# Using Make
make install

# Or manually
uv pip install -e ".[dev]"
```

## Project Structure

The NoETL project has the following structure:

```
noetl/
├── bin/                  # Scripts for development and deployment
├── catalog/              # Default catalog for playbooks
├── data/                 # Data files for examples and tests
├── docs/                 # Documentation
├── noetl/                # Main package
│   ├── agent/            # Agent for executing playbooks
│   ├── api/              # API for interacting with NoETL
│   ├── catalog/          # Catalog for managing playbooks
│   ├── cli/              # Command-line interface
│   ├── core/             # Core functionality
│   ├── tasks/            # Task implementations
│   ├── utils/            # Utility functions
│   └── workflow/         # Workflow engine
├── playbook/             # Example playbooks
├── tools/                # Developer tools and scripts (build, versioning); PyPI helpers under tools/pypi
├── tests/                # Tests
└── ui/                   # Web UI
```

## Development Workflow

### Unified Platform Development (Recommended)

```bash
# Deploy/redeploy the complete platform
make unified-deploy

# Complete recreation for clean state
make unified-recreate-all

# Check platform health after changes
make unified-health-check

# View logs
kubectl logs -f -n noetl-platform -l app=noetl,component=server
kubectl logs -f -n noetl-platform -l app=noetl-worker,component=worker

# Access services
# NoETL API: http://localhost:30082/api/health
# Grafana: http://localhost:3000 (admin/admin)
# Metrics: http://localhost:8428/vmui/
```

### Local Python Development

#### Running Tests

```bash
# Run all tests
pytest

# Run tests with coverage
pytest --cov=noetl

# Run specific tests
pytest tests/test_agent.py

# Using Make
make test
```

#### Running the Server Locally

```bash
# Run the server in development mode
noetl server --reload

# Or using Make
make run
```

### Building the Package

```bash
# Build the package
make build-package

# Or manually
python -m build
```

### Code Style

NoETL follows the PEP 8 style guide. You can check your code style using:

```bash
# Check code style
make lint

# Or manually
flake8 noetl tests
```

## Contributing

### Submitting Changes

1. Fork the repository
2. Create a new branch for your changes
3. Make your changes
4. Run tests to ensure your changes don't break existing functionality
5. Submit a pull request

### Pull Request Process

1. Ensure your code follows the project's style guide
2. Update the documentation to reflect any changes
3. Include tests for new functionality
4. Ensure all tests pass
5. Submit a pull request with a clear description of the changes

## Building and Publishing to PyPI

### Building the Package

```bash
# Build the package
make build-package

# Or manually
python -m build
```

This will create distribution files in the `dist/` directory.

### Testing the Package

You can test the package locally before publishing:

```bash
# Install the package locally
pip install dist/noetl-*.whl

# Test the package
noetl --version
```

### Publishing to PyPI

NoETL provides scripts for publishing to PyPI:

```bash
# Publish to TestPyPI
./tools/pypi/pypi_publish.sh --test <version>

# Publish to PyPI
./tools/pypi/pypi_publish.sh <version>

# Interactive publishing wizard
./tools/pypi/interactive_publish.sh
```

For more detailed instructions, see the [PyPI Publishing Guide](pypi_manual.md).

## Docker Development

### Building the Docker Image

```bash
# Build the Docker image
docker build -t noetl:dev .

# Or using Make
make build
```

### Running NoETL in Docker

```bash
# Run the NoETL server in Docker
docker run -p 8082:8082 noetl:dev

# Or using Make
make up
```

### Running Tests in Docker

```bash
# Run tests in Docker
docker run noetl:dev pytest

# Or using Make
make test
```

## Debugging

### Using the Debug Mode

You can run NoETL in debug mode to get more detailed logs:

```bash
# Run the agent in debug mode
noetl agent -f playbooks.yaml --debug

# Run the server in debug mode
noetl server --reload --debug
```

### Using a Debugger

You can use a debugger like `pdb` or an IDE debugger to debug NoETL:

```bash
# Using pdb
python -m pdb -c continue noetl/agent.py -f playbooks.yaml
```

## Next Steps

- [Installation Guide](installation.md) - Learn about other installation methods
- [CLI Usage Guide](cli_usage.md) - Learn how to use the NoETL command-line interface
- [API Usage Guide](api_usage.md) - Learn how to use the NoETL REST API
- [PyPI Publishing Guide](pypi_manual.md) - Learn how to build and publish the NoETL package to PyPI