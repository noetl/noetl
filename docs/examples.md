# NoETL Examples Guide

This guide provides references to NoETL playbook examples and their detailed documentation.

## Overview

NoETL includes several example playbooks that demonstrate different capabilities of the framework. These examples help to understand how to use NoETL for various data processing and automation tasks.

Each example has:
- A playbook file (YAML) in the `playbook/` directory
- Detailed documentation in the `docs/examples/` directory

## Basic Examples

### Weather API Example

This example fetches weather data for a city and checks if the temperature exceeds a threshold.

- **Playbook**: [weather.yaml](../playbook/weather.yaml)
- **Documentation**: [Weather Example Documentation](examples/weather_example.md)

**Key Features:**
- Fetching data from external API
- Conditional workflow branching
- Template variable usage
- Python task execution

### Weather Example with Loops

This example demonstrates an advanced weather data workflow that iterates over multiple cities, fetches weather data for each, and processes city districts.

- **Playbook**: [weather_example.yaml](../playbook/weather_example.yaml)
- **Documentation**: [Weather Example with Loops Documentation](examples/weather_loop_example.md)

**Key Features:**
- Iterating over collections using loops
- Nested loops for hierarchical data processing
- Conditional workflow branching
- Filtering loop items with conditions
- Aggregating results from multiple iterations

## Database Examples

### Postres JSONB Example

This example demonstrates how to work with Postres JSONB data type.

- **Playbook**: [postgres_test.yaml](../playbook/postgres_test.yaml)
- **Documentation**: [Postres JSONB Example Documentation](examples/postgres_test_example.md)

**Key Features:**
- Working with Postres JSONB data type
- Creating and using Postres functions
- Querying and filtering JSON data
- Updating JSON fields

### DuckDB Dictionary Loading Example

This example demonstrates how to use DuckDB to load dictionary data and interact with a Postres database.

- **Playbook**: [load_dict_test.yaml](../playbook/load_dict_test.yaml)
- **Documentation**: [DuckDB Dictionary Loading Example Documentation](examples/load_dict_test_example.md)

**Key Features:**
- Loading dictionary data into DuckDB
- Connecting to Postres from DuckDB
- Creating tables in both DuckDB and Postres
- Transferring data between databases

## Cloud Integration Examples

### Google Cloud Storage Secrets Example

This example demonstrates how to use Google Cloud Secret Manager to securely access Google Cloud Storage.

- **Playbook**: [gcs_secrets_example.yaml](../playbook/gcs_secrets_example.yaml)
- **Documentation**: [GCS Secrets Example Documentation](examples/gcs_secrets_example.md)

**Key Features:**
- Retrieving GCS HMAC credentials from Google Secret Manager
- Creating a DuckDB secret for GCS authentication
- Using the secret for GCS operations
- Secure handling of cloud storage credentials

## Advanced Examples

### Multi-Playbook Example

This example demonstrates how to use multiple playbooks together, with one playbook calling another.

- **Playbook**: [multi_playbook_example.yaml](../playbook/multi_playbook_example.yaml)
- **Documentation**: [Multi-Playbook Example Documentation](examples/multi_playbook_example.md)

**Key Features:**
- Calling one playbook from another
- Passing parameters between playbooks
- Organizing complex workflows into modular components
- Reusing playbook components

### Secrets Test Example

This example demonstrates how to work with secrets in NoETL.

- **Playbook**: [secrets_test.yaml](../playbook/secrets_test.yaml)
- **Documentation**: [Secrets Test Example Documentation](examples/secrets_test_example.md)

**Key Features:**
- Managing secrets securely
- Retrieving secrets from different providers
- Using secrets in database connections
- Secure credential handling

## Integration Examples

### Google Storage, DuckDB, and Postres Integration

This example demonstrates how to integrate Google Cloud Storage, DuckDB, and Postres for data processing.

- **Playbook**: [gs_duckdb_postgres_example.yaml](../playbook/gs_duckdb_postgres_example.yaml)
- **Documentation**: [GS DuckDB Postgres Example Documentation](examples/gs_duckdb_postgres_example.md)

**Key Features:**
- Integration between Google Cloud Storage, DuckDB, and Postres
- Data conversion between CSV and Parquet formats
- Secret management for secure authentication
- Advanced file operations with DuckDB
- Database table creation and data loading



## Summary of Available Examples

| Category | Example | Playbook | Documentation |
|----------|---------|----------|--------------|
| **Basic** | Weather API | [weather.yaml](../playbook/weather.yaml) | [Weather Example](examples/weather_example.md) |
| **Basic** | Weather with Loops | [weather_example.yaml](../playbook/weather_example.yaml) | [Weather Example with Loops](examples/weather_loop_example.md) |
| **Database** | Postres JSONB | [postgres_test.yaml](../playbook/postgres_test.yaml) | [Postres JSONB Example](examples/postgres_test_example.md) |
| **Database** | DuckDB Dictionary Loading | [load_dict_test.yaml](../playbook/load_dict_test.yaml) | [DuckDB Dictionary Loading Example](examples/load_dict_test_example.md) |
| **Cloud** | GCS Secrets | [gcs_secrets_example.yaml](../playbook/gcs_secrets_example.yaml) | [GCS Secrets Example](examples/gcs_secrets_example.md) |
| **Advanced** | Multi-Playbook | [multi_playbook_example.yaml](../playbook/multi_playbook_example.yaml) | [Multi-Playbook Example](examples/multi_playbook_example.md) |
| **Advanced** | Secrets Test | [secrets_test.yaml](../playbook/secrets_test.yaml) | [Secrets Test Example](examples/secrets_test_example.md) |
| **Integration** | GS DuckDB Postgres | [gs_duckdb_postgres_example.yaml](../playbook/gs_duckdb_postgres_example.yaml) | [GS DuckDB Postgres Example](examples/gs_duckdb_postgres_example.md) |

## Next Steps

- [Playbook Structure](playbook_structure.md) - Learn how to structure NoETL playbooks
- [Workflow Tasks](action_type.md) - Learn about available tasks and their parameters
- [CLI Usage Guide](cli_usage.md) - Learn how to use the NoETL command-line interface
- [API Usage Guide](api_usage.md) - Learn how to use the NoETL REST API
