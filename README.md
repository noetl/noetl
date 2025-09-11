# Not Only ETL

__NoETL__ is an automation framework for data processing and MLOps orchestration.

[![PyPI version](https://badge.fury.io/py/noetl.svg)](https://badge.fury.io/py/noetl)
[![Python Version](https://img.shields.io/pypi/pyversions/noetl.svg)](https://pypi.org/project/noetl/)
[![License](https://img.shields.io/pypi/l/noetl.svg)](https://github.com/noetl/noetl/blob/main/LICENSE)

## System Architecture

The following diagram illustrates the main components and intent of the NoETL system:

![NoETL System Diagram](docs/images/NoETL.png)

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
- For Windows users (in PowerShell)
  ```bash
  python -m venv .venv
  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
  .venv\Scripts\Activate.ps1
  pip install noetl
  ```
- Install a specific version
  ```bash
  pip install noetl==0.1.24
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
# Start the server with default settings
noetl server

#  use the explicit start command with options
noetl server start --host 0.0.0.0 --port 8080 --workers 4 --debug

# Stop the server
noetl server stop

# Force stop without confirmation
noetl server stop --force
```

The server starts on http://localhost:8080 by default. You can customize the host, port, number of workers, and enable debug mode using command options.

### 2. Using the Command Line

NoETL provides a streamlined command-line interface for managing and executing playbooks:

- Register a playbook in the catalog
```bash
noetl register ./path/to/playbook.yaml
```

- List playbooks in the catalog
```bash
noetl catalog list playbook
```

- Execute a registered playbook
```bash
noetl execute my_playbook --version 0.1.0
```

- Register and execute with the catalog command
```bash
noetl catalog register ./path/to/playbook.yaml
noetl catalog execute my_playbook --version 0.1.0
```

### 3. Docker Deployment

For containerized deployment:

```bash
# Pull the latest image
docker pull noetl/noetl:latest

# Start the server
docker run -p 8080:8080 noetl/noetl:latest

# with environment variables
docker run -p 8080:8080 -e NOETL_RUN_MODE=server noetl/noetl:latest

# Stop the server
docker run -e NOETL_RUN_MODE=server-stop -e NOETL_FORCE_STOP=true noetl/noetl:latest
```

### 4. Kubernetes Deployment

For Kubernetes deployment using Kind (Kubernetes in Docker):

```bash
# Follow the instructions in k8s/README.md
# Or use the automated deployment script
./k8s/deploy-kind.sh

# To stop the server in Kubernetes, create a job:
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: noetl-server-stop
spec:
  template:
    spec:
      containers:
      - name: noetl-stop
        image: noetl:latest
        env:
        - name: NOETL_RUN_MODE
          value: "server-stop"
        - name: NOETL_FORCE_STOP
          value: "true"
      restartPolicy: Never
  backoffLimit: 1
EOF
```

See [Kubernetes Deployment Guide](k8s/KIND-README.md) for detailed instructions.

## Deploy: Server + Worker Pools (CPU and QPU)

Below are practical ways to deploy the NoETL server and run workers.

Option A — Local (Docker Compose) quick start
- Start Postgres and the NoETL server (exposes API and built-in Worker API):
  - docker compose up -d database pip-api
  - Server will listen on http://localhost:8084 and include /api/worker endpoints.
- Register example playbooks:
  - ./bin/register_playbook_examples.sh 8084 localhost
- Execute a playbook via the server API/CLI:
  - noetl execute --path "weather/weather_example" --host localhost --port 8084 --payload '{}'
- Notes:
  - In simple/local setups, the server’s built-in Worker API handles task execution; no separate worker containers are required.
  - Health check: curl http://localhost:8084/health

Optional (Local) — Run separate worker processes
- You can spin up separate worker API processes on different ports and point the Broker to them via env vars:
  - CPU worker:
    - NOETL_ENABLE_WORKER_API=true noetl server start --host 0.0.0.0 --port 18084
  - QPU worker (requires quantum SDKs installed; e.g., pip install "qiskit>=1.0" "qiskit-ibm-runtime>=0.23"):
    - export QISKIT_IBM_TOKEN=...; export QISKIT_IBM_INSTANCE=...
    - NOETL_ENABLE_WORKER_API=true noetl server start --host 0.0.0.0 --port 18085
  - In your server environment (port 8084), set:
    - NOETL_WORKER_CPU_URL=http://localhost:18084
    - NOETL_WORKER_QPU_URL=http://localhost:18085
  - Now the Broker will route tasks to the appropriate worker endpoints.

Option B — Kubernetes (recommended for separate CPU/QPU pools)
- Prerequisites:
  - Build/push images as needed (especially the QPU worker image docker/noetl/worker-qpu/Dockerfile if using QPU).
  - Create your noetl-secret and (optional) ibm-quantum-secret.
- Apply resources with Makefile targets (set NAMESPACE=your-namespace):
  - make k8s-noetl-apply NAMESPACE=your-ns
    - This applies ConfigMap, Services (server, CPU worker, QPU worker), and Deployments.
  - Validate:
    - kubectl get pods -n your-ns -l app=noetl
    - kubectl get pods -n your-ns -l app=noetl-worker
    - kubectl port-forward -n your-ns deploy/noetl 8084:8084
    - curl http://localhost:8084/health
  - Register and execute:
    - noetl register examples/weather/weather_example.yaml --host localhost --port 8084
    - noetl execute --path "weather/weather_example" --host localhost --port 8084 --payload '{}'
- Details and advanced guidance (node labels, taints, QPU credentials, in-cluster URLs):
  - See k8s/docs/worker_pools.md

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

For examples of NoETL playbooks and detailed explanations, see the [Examples Guide](https://github.com/noetl/noetl/blob/master/docs/examples.md).

To run a playbook:

```bash
noetl agent -f path/to/playbooks.yaml
```

## Documentation

For more detailed information, please refer to the following documentation:

> **Note:**  
> When installed from PyPI, the `docs` folder is included in your local package.  
> You can find all documentation files in the `docs/` directory of your installed package.

### Getting Started
- [Installation Guide](https://github.com/noetl/noetl/blob/master/docs/installation.md) - Installation instructions
- [CLI Usage Guide](https://github.com/noetl/noetl/blob/master/docs/cli_usage.md) - Commandline interface usage
- [API Usage Guide](https://github.com/noetl/noetl/blob/master/docs/api_usage.md) - REST API usage
- [Docker Usage Guide](https://github.com/noetl/noetl/blob/master/docs/docker_usage.md) - Docker deployment

### Core Concepts
- [Playbook Structure](https://github.com/noetl/noetl/blob/master/docs/playbook_structure.md) - Structure of NoETL playbooks
- [Workflow Tasks](https://github.com/noetl/noetl/blob/master/docs/action_type.md) - Action types and parameters
- [Environment Configuration](https://github.com/noetl/noetl/blob/master/docs/environment_variables.md) - Setting up environment variables


### Examples

NoETL includes several example playbooks that demonstrate some capabilities:

- **Weather API Integration** - Fetches and processes weather data from external APIs
- **Database Operations** - Demonstrates Postgres and DuckDB integration
- **Google Cloud Storage** - A secure cloud storage operations with Google Cloud
- **Secrets Management** - Illustrates secure handling of credentials and sensitive data
- **Multi-Playbook Workflows** - Complex workflow orchestration

For detailed examples, see the [Examples Guide](https://github.com/noetl/noetl/blob/master/docs/examples.md).

## Credentials and Secrets

NoETL supports encrypted credentials/secrets storage and convenient usage in playbooks.

- Encryption: AES-256-GCM with key derived from NOETL_ENCRYPTION_KEY (n8n-compatible format)
- Storage: Postgres table `credential` (singular)
- API: POST/GET /api/credentials, GET /api/credentials/{name|id}
- CLI: `noetl secret register` (inline JSON or from file)
- Manifest: `noetl catalog register secret examples/credentials/secret_bearer.yaml`
- HTTP tasks: n8n-like auth injection via `authentication: genericCredentialType` and `genericAuthType: httpBearerAuth`
- GCP tokens: `POST /api/gcp/token` or `secrets` task provider `gcp_token`; helper `bin/test-gcp-token.sh`

See the full guide with step-by-step examples:
- docs/credentials_and_secrets.md

Quick examples:

```bash
# Register a bearer token (CLI)
noetl secret register -n my-bearer-token -t httpBearerAuth --data '{"token":"XYZ"}'

# Register via manifest
noetl catalog register secret examples/credentials/secret_bearer.yaml --host localhost --port 8084

# Use in HTTP task (playbook): examples/credentials/http_bearer_example.yaml
noetl execute examples/credentials/http_bearer_example.yaml --host localhost --port 8084

# Test GCP token endpoint
./bin/test-gcp-token.sh --port 8084 --credentials-path .secrets/noetl-service-account.json
```

## Development

For information about contributing to NoETL or building from source:

- [Development Guide](https://github.com/noetl/noetl/blob/master/docs/development.md) - Setting up a development environment
- [PyPI Publishing Guide](https://github.com/noetl/noetl/blob/master/docs/pypi_manual.md) - Building and publishing to PyPI

## Community & Support

- **GitHub Issues**: [Report bugs or request features](https://github.com/noetl/noetl/issues)
- **Documentation**: [Full documentation](https://noetl.io/docs)
- **Website**: [https://noetl.io](https://noetl.io)

## License

NoETL is released under the MIT License. See the [LICENSE](LICENSE) file for details.


## Diagram generation (PlantUML, SVG/PNG)
Generate a DAG diagram from a NoETL playbook.

Usage:

- Print PlantUML to stdout:
  `noetl diagram /path/to/playbook.yaml`

- Save PlantUML to a .puml:
  `noetl diagram /path/to/playbook.yaml -o playbook.puml`

- Render directly to SVG:
  `noetl diagram /path/to/playbook.yaml -f svg -o playbook.svg`

- Render directly to PNG:
  `noetl diagram /path/to/playbook.yaml -f png -o playbook.png`

- Render an existing .puml file to SVG:
  `noetl diagram /path/to/playbook.puml -f svg -o playbook.svg`

Tips:
- If you omit --output for image formats, the output filename is derived from the input (e.g., path/to/playbook.svg).
- Set NOETL_KROKI_URL to use a self-hosted Kroki server (default is https://kroki.io).

Example with the provided weather playbook:
  `noetl diagram examples/weather/weather_loop_example.yaml -f svg -o weather_loop_example.svg`

Using makefile:
  ` make diagram PLAYBOOK=examples/weather/weather_loop_example.yaml FORMAT=svg`
