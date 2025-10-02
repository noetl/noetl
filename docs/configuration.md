# NoETL Configuration

NoETL uses a centralized configuration system based on Pydantic. This document describes how to configure NoETL using environment variables and the `.env` file.

## Configuration Settings

All NoETL settings are defined in the `Settings` class in `noetl/config.py`. The settings are loaded from environment variables and can be overridden by command line arguments.

### Application Settings

| Setting | Environment Variable | Default | Description |
|---------|---------------------|---------|-------------|
| `app_name` | `NOETL_APP_NAME` | `"NoETL"` | Application name |
| `app_version` | `NOETL_APP_VERSION` | `"1.0.0"` | Application version |
| `debug` | `NOETL_DEBUG` | `False` | Enable debug mode |
| `host` | `NOETL_HOST` | `"0.0.0.0"` | Server host |
| `port` | `NOETL_PORT` | `8080` | Server port |
| `enable_ui` | `NOETL_ENABLE_UI` | `True` | Enable UI components |
| `run_mode` | `NOETL_RUN_MODE` | `"server"` | Run mode (server, worker, or cli) |

### Worker Settings

| Setting | Environment Variable | Default | Description |
|---------|---------------------|---------|-------------|
| `playbook_path` | `NOETL_PLAYBOOK_PATH` | `None` | Path to the playbook file |
| `playbook_version` | `NOETL_PLAYBOOK_VERSION` | `None` | Version of the playbook to execute |
| `mock_mode` | `NOETL_MOCK_MODE` | `False` | Run in mock mode |

### Database Settings

| Setting | Environment Variable | Default | Description |
|---------|---------------------|---------|-------------|
| `postgres_user` | `POSTGRES_USER` or `NOETL_POSTGRES_USER` | `"noetl"` | PostgreSQL username |
| `postgres_password` | `POSTGRES_PASSWORD` or `NOETL_POSTGRES_PASSWORD` | `"noetl"` | PostgreSQL password |
| `postgres_host` | `POSTGRES_HOST` or `NOETL_POSTGRES_HOST` | `"localhost"` | PostgreSQL host |
| `postgres_port` | `POSTGRES_PORT` or `NOETL_POSTGRES_PORT` | `5432` | PostgreSQL port |
| `postgres_db` | `POSTGRES_DB` or `NOETL_POSTGRES_DB` | `"noetl"` | PostgreSQL database name |
| `postgres_schema` | `POSTGRES_SCHEMA` or `NOETL_POSTGRES_SCHEMA` | `"noetl"` | PostgreSQL schema |

### Admin Database Settings

| Setting | Environment Variable | Default | Description |
|---------|---------------------|---------|-------------|
| `admin_postgres_user` | `POSTGRES_USER` | `"postgres"` | Admin PostgreSQL username |
| `admin_postgres_password` | `POSTGRES_PASSWORD` | `"postgres"` | Admin PostgreSQL password |

### Other Settings

| Setting | Environment Variable | Default | Description |
|---------|---------------------|---------|-------------|
| `data_dir` | `NOETL_DATA_DIR` | `"./data"` | Data directory |

## Using Environment Variables

You can configure NoETL by setting environment variables before running the application:

```bash
# Server settings
export NOETL_HOST="0.0.0.0"
export NOETL_PORT="8080"
export NOETL_DEBUG="true"
export NOETL_ENABLE_UI="true"

# Database settings
export POSTGRES_USER="noetl"
export POSTGRES_PASSWORD="noetl"
export POSTGRES_HOST="localhost"
export POSTGRES_PORT="5432"
export POSTGRES_DB="noetl"

# Run the application
noetl server
```

## Using .env File

You can also create a `.env` file in the project root directory with the same environment variables:

```
# Server settings
NOETL_HOST=0.0.0.0
NOETL_PORT=8080
NOETL_DEBUG=true
NOETL_ENABLE_UI=true

# Database settings
POSTGRES_USER=noetl
POSTGRES_PASSWORD=noetl
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=noetl
```

## Docker and Kubernetes Configuration

When running NoETL in Docker or Kubernetes, you can set environment variables in the configuration files:

### Docker Compose

```yaml
services:
  noetl:
    image: noetl:latest
    environment:
      NOETL_HOST: "0.0.0.0"
      NOETL_PORT: "8080"
      NOETL_DEBUG: "true"
      POSTGRES_USER: "noetl"
      POSTGRES_PASSWORD: "noetl"
      POSTGRES_HOST: "database"
      POSTGRES_PORT: "5432"
      POSTGRES_DB: "noetl"
```

### Kubernetes

```yaml
containers:
- name: noetl
  image: noetl:latest
  env:
  - name: NOETL_HOST
    value: "0.0.0.0"
  - name: NOETL_PORT
    value: "8080"
  - name: NOETL_DEBUG
    value: "true"
  - name: POSTGRES_USER
    valueFrom:
      secretKeyRef:
        name: postgres-credentials
        key: username
  - name: POSTGRES_PASSWORD
    valueFrom:
      secretKeyRef:
        name: postgres-credentials
        key: password
```

## Accessing Settings in Code

You can access the settings in your code by importing the `settings` instance:

```python
from noetl.config import settings

# Access settings
host = settings.host
port = settings.port
debug = settings.debug

# Get database URL
db_url = settings.get_database_url()

# Get connection string
conn_string = settings.get_pgdb_connection_string()
```

## Command Line Arguments

When using the command line interface, command line arguments will override environment variables:

```bash
noetl server --host 127.0.0.1 --port 9090 --debug
```

In this example, the `host`, `port`, and `debug` settings will be set to the values provided in the command line arguments, regardless of the environment variables.