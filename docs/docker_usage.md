# NoETL Docker Usage Guide

This guide provides detailed instructions for using NoETL with Docker.

## Overview

NoETL can be run in Docker containers, which provides several benefits:

- Consistent environment across different platforms
- Easy deployment
- Isolation from the host system
- Simplified dependency management

## Prerequisites

- Docker installed on your system
- Docker Compose (optional, for multi-container setups)

## Quick Start

### Using the Official Docker Image

The simplest way to run NoETL in Docker is to use the official Docker image:

```bash
# Pull the latest NoETL image
docker pull noetl/noetl:latest

# Run the NoETL server
docker run -p 8082:8082 noetl/noetl:latest
```

This will start the NoETL server and expose it on port 8082 of your host machine.

### Building and Running from Source

If you want to build the Docker image from source:

1. Clone the repository:
   ```bash
   git clone https://github.com/noetl/noetl.git
   cd noetl
   ```

2. Build the Docker image:
   ```bash
   docker build -t noetl:local .
   ```

3. Run the NoETL server:
   ```bash
   docker run -p 8082:8082 noetl:local
   ```

## Using Docker Compose

NoETL provides a Docker Compose configuration that sets up a complete environment with PostgreSQL:

1. Start the containers:
   ```bash
   docker-compose up
   ```

2. Or build and start the containers:
   ```bash
   docker-compose up --build
   ```

3. To run in detached mode:
   ```bash
   docker-compose up -d
   ```

4. To stop the containers:
   ```bash
   docker-compose down
   ```

## Using the Makefile

NoETL provides a Makefile with convenient commands for Docker operations:

```bash
# Build the Docker containers
make build

# Start the Docker containers
make up

# Stop the Docker containers
make down

# View logs
make logs

# Run tests in Docker
make test
```

## Accessing the NoETL Server

Once the NoETL server is running in Docker, you can access it at:

- Web UI: `http://localhost:8082`
- API: `http://localhost:8082/api`

## Running Playbooks in Docker

### Using the CLI

You can execute NoETL commands inside the Docker container:

```bash
# Execute a playbook directly
docker exec -it noetl noetl agent -f /path/to/playbook.yaml

# Register a playbook in the catalog
docker exec -it noetl noetl playbook --register /path/to/playbook.yaml

# Execute a playbook from the catalog
docker exec -it noetl noetl playbook --execute --path "workflows/example/playbook"
```

### Using the API

You can also use the NoETL API to execute playbooks:

```bash
# Register a playbook
curl -X POST "http://localhost:8082/catalog/register" \
  -H "Content-Type: application/json" \
  -d '{
    "content_base64": "'"$(base64 -i ./path/to/playbook.yaml)"'"
  }'

# Execute a playbook
curl -X POST "http://localhost:8082/playbook/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "path": "workflows/example/playbook",
    "version": "0.1.0",
    "input_payload": {
      "param1": "value1",
      "param2": "value2"
    }
  }'
```

## Mounting Volumes

You can mount volumes to persist data and share files with the Docker container:

```bash
docker run -p 8082:8082 \
  -v $(pwd)/playbooks:/app/playbooks \
  -v $(pwd)/data:/app/data \
  noetl/noetl:latest
```

This mounts the local `playbooks` and `data` directories to the corresponding directories in the Docker container.

## Environment Variables

You can pass environment variables to the Docker container:

```bash
docker run -p 8082:8082 \
  -e POSTGRES_HOST=postgres \
  -e POSTGRES_PORT=5432 \
  -e POSTGRES_USER=noetl \
  -e POSTGRES_PASSWORD=noetl \
  -e POSTGRES_DB=noetl \
  noetl/noetl:latest
```

## Docker Compose Configuration

The default `docker-compose.yaml` file includes the following services:

- `noetl`: The NoETL server
- `postgres`: PostgreSQL database for storing playbook data

You can customize the Docker Compose configuration by editing the `docker-compose.yaml` file.

## Customizing the Docker Image

If you need to customize the Docker image, you can create your own Dockerfile based on the official NoETL image:

```dockerfile
FROM noetl/noetl:latest

# Install additional dependencies
RUN pip install some-package

# Add custom files
COPY ./custom_playbooks /app/playbooks

# Set environment variables
ENV SOME_VARIABLE=some_value

# Set the working directory
WORKDIR /app

# Set the entrypoint
ENTRYPOINT ["noetl", "server"]
```

## Troubleshooting

### Container Fails to Start

If the container fails to start, check the logs:

```bash
docker logs noetl
```

### Cannot Connect to the Server

If you cannot connect to the NoETL server, check that the port is correctly mapped:

```bash
docker ps
```

Make sure the container is running and the port mapping is correct (e.g., `0.0.0.0:8082->8082/tcp`).

### Database Connection Issues

If NoETL cannot connect to the PostgreSQL database, check the environment variables and network configuration:

```bash
# Check the network
docker network ls
docker network inspect noetl_default

# Check the PostgreSQL container
docker logs postgres
```

## Next Steps

- [Installation Guide](installation.md) - Learn about other installation methods
- [CLI Usage Guide](cli_usage.md) - Learn how to use the NoETL command-line interface
- [API Usage Guide](api_usage.md) - Learn how to use the NoETL REST API
- [Playbook Structure](playbook_structure.md) - Learn how to structure NoETL playbooks