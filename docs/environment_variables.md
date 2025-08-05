# NoETL Environment Variables

This document provides a comprehensive list of environment variables supported by NoETL.

## Server Configuration

| Variable | Description | Default Value |
|----------|-------------|---------------|
| `NOETL_HOST` | Host address for the NoETL server | `localhost` |
| `NOETL_PORT` | Port for the NoETL server | `8080` |
| `NOETL_ENABLE_UI` | Enable or disable the UI components | `true` |
| `LOG_LEVEL` | Logging level (INFO, DEBUG, WARNING, ERROR) | `INFO` |
| `NOETL_DATA_DIR` | Directory for NoETL data files | `data` |

## Database Configuration

NoETL supports two sets of database configuration variables. The application will first try to use the NOETL_* variables, and if not available, it will fall back to the POSTGRES_* variables.

### NoETL-specific Database Variables

| Variable | Description | Default Value |
|----------|-------------|---------------|
| `NOETL_USER` | Username for NoETL database connection | `noetl` |
| `NOETL_PASSWORD` | Password for NoETL database connection | `noetl` |
| `NOETL_SCHEMA` | Schema for NoETL database connection | `noetl` |

### PostgreSQL Database Variables

| Variable | Description | Default Value |
|----------|-------------|---------------|
| `POSTGRES_USER` | Username for PostgreSQL database connection | `noetl` |
| `POSTGRES_PASSWORD` | Password for PostgreSQL database connection | `noetl` |
| `POSTGRES_DB` | Database name for PostgreSQL connection | `noetl` |
| `POSTGRES_HOST` | Host address for PostgreSQL server | `localhost` |
| `POSTGRES_PORT` | Port for PostgreSQL server | `5432` |
| `POSTGRES_SCHEMA` | Schema for PostgreSQL database connection | `public` |

## Google Cloud Configuration

| Variable | Description |
|----------|-------------|
| `GOOGLE_CLOUD_PROJECT` | Google Cloud project ID |
| `SERVICE_ACCOUNT_EMAIL` | Service account email for Google Cloud |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to Google Cloud service account credentials file |
| `GOOGLE_SECRET_POSTGRES_PASSWORD` | Secret Manager path for PostgreSQL password |
| `GOOGLE_SECRET_API_KEY` | Secret Manager path for API key |
| `GCS_ENDPOINT` | Google Cloud Storage endpoint |
| `GCS_REGION` | Google Cloud region |

## Other Configuration

| Variable | Description | Default Value |
|----------|-------------|---------------|
| `TZ` | Timezone | `America/Chicago` |
| `PYTHONPATH` | Python module search path | `/opt/noetl` |
| `JUPYTER_TOKEN` | Token for Jupyter notebook authentication | `noetl` |
| `VITE_API_BASE_URL` | Base URL for API calls from the UI | `/api` |

## Usage in Kubernetes

In Kubernetes deployments, these environment variables are set in the ConfigMap and Secret resources:

- `noetl-configmap.yaml`: Contains non-sensitive configuration
- `noetl-secret.yaml`: Contains sensitive information like passwords

The deployment uses these environment variables to configure the NoETL server and its connections to the database.