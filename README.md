# Not Only ETL

__NoETL__ is an automation framework for data processing and MLOps orchestration.

[![PyPI version](https://badge.fury.io/py/noetl.svg)](https://badge.fury.io/py/noetl)
[![Python Version](https://img.shields.io/pypi/pyversions/noetl.svg)](https://pypi.org/project/noetl/)
[![License](https://img.shields.io/pypi/l/noetl.svg)](https://github.com/noetl/noetl/blob/main/LICENSE)

## Quick Start

### Installation

- Install NoETL from PyPI:
  ```bash
  pip install noetl
  ```

For development or specific versions:
- Install in a virtual environment
  ```bash
  python -m venv .venv
  source .venv/bin/activate
  pip install noetl
  ```
- Install a specific version
  ```bash
  pip install noetl==0.1.18
  ```

### Prerequisites

- Python 3.11+
- For full functionality:
  - Postgres database (mandatory, for event log persistent storage and NoETL system metadata)
  - Docker (optional, for containerized development and deployment)

## Basic Usage

After installing NoETL:

### 1. Run the NoETL Server

Start the NoETL server to access the web UI and REST API:

```bash
noetl server
```

This starts the server on http://localhost:8082 by default.

### 2. Using the Command Line

NoETL has a command-line interface for executing playbooks:

- Register a playbook in the catalog
```bash
noetl playbook --register ./<path to playbook folder>/playbook.yaml
```
- Execute a playbook from the catalog
```bash
noetl playbook --execute --path "workflows/example/playbook"
```
- Execute a playbook directly
```bash
noetl agent -f ./<path to playbook folder>/playbook.yaml
```

### 3. Docker Deployment

For containerized deployment:

```bash
docker pull noetl/noetl:latest
docker run -p 8082:8082 noetl/noetl:latest
```

## Workflow DSL Structure

NoETL uses a declarative YAML-based Domain Specific Language (DSL) for defining workflows. The key components of a NoETL playbook include:

- **Metadata**: Version, path, and description of the playbook
- **Workload**: Input data and parameters for the workflow
- **Workflow**: A list of steps that make up the workflow, where each step is defined with `step: step_name`, including:
  - **Steps**: Individual operations in the workflow
  - **Tasks**: Actions performed at each step (HTTP requests, database operations, Python code)
  - **Transitions**: Rules for moving between steps
  - **Conditions**: Logic for branching the workflow
- **Workbook**: Reusable task definitions that can be called from workflow steps, including:
  - **Task Types**: Python, HTTP, DuckDB, PostgreSQL, Secret.
  - **Parameters**: Input parameters for the tasks
  - **Code**: Implementation of the tasks

For examples of NoETL playbooks and detailed explanations, see the [Examples Guide](docs/examples.md).

To run a playbook:

```bash
noetl agent -f path/to/playbook.yaml
```

## Documentation

For more detailed information, please refer to the following documentation:

### Getting Started
- [Installation Guide](docs/installation.md) - Installation instructions
- [CLI Usage Guide](docs/cli_usage.md) - Commandline interface usage
- [API Usage Guide](docs/api_usage.md) - REST API usage
- [Docker Usage Guide](docs/docker_usage.md) - Docker deployment

### Core Concepts
- [Playbook Structure](docs/playbook_structure.md) - Structure of NoETL playbooks
- [Workflow Tasks](docs/action_type.md) - Action types and parameters
- [Environment Configuration](docs/environment_variables.md) - Setting up environment variables


### Advanced Examples

NoETL includes several example playbooks that demonstrate more advanced capabilities:

- **Weather API Integration** - Fetches and processes weather data from external APIs
- **Database Operations** - Demonstrates Postgres and DuckDB integration
- **Google Cloud Storage** - Shows secure cloud storage operations with Google Cloud
- **Secrets Management** - Illustrates secure handling of credentials and sensitive data
- **Multi-Playbook Workflows** - Demonstrates complex workflow orchestration

For detailed examples, see the [Examples Guide](docs/examples.md).

## Development

For information about contributing to NoETL or building from source:

- [Development Guide](docs/development.md) - Setting up a development environment
- [PyPI Publishing Guide](docs/pypi_manual.md) - Building and publishing to PyPI

## Community & Support

- **GitHub Issues**: [Report bugs or request features](https://github.com/noetl/noetl/issues)
- **Documentation**: [Full documentation](https://noetl.io/docs)
- **Website**: [https://noetl.io](https://noetl.io)

## License

NoETL is released under the MIT License. See the [LICENSE](LICENSE) file for details.
