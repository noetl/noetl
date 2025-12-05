# NoETL Test Fixtures Guide

This guide provides references to NoETL test fixture playbooks that demonstrate different capabilities of the framework. These test fixtures help to understand how to use NoETL for various data processing and automation tasks.

Each test fixture has:
- A playbook file (YAML) in the `tests/fixtures/playbooks/` directory
- Comprehensive test coverage

## Basic Examples

### Weather Control Flow Example

This example demonstrates conditional workflow branching based on temperature thresholds.

- **Playbook**: [weather_control_flow.yaml](../tests/fixtures/playbooks/control_flow/weather_control_flow/weather_control_flow.yaml)

**Key Features:**
- Conditional workflow branching with `when/then/else`
- Template variable usage
- Python task execution

- **Playbook**: [weather_example.yaml](../examples/weather/weather_loop_example.yaml)
- **Documentation**: [Weather Example with Loops Documentation](examples/weather_loop_example.md)

**Key Features:**
- Iterating over collections using loops
- Nested loops for hierarchical data processing
- Conditional workflow branching
- Filtering loop items with conditions
- Aggregating results from multiple iterations

## Database Examples

### PostgreSQL JSONB Example

This example demonstrates how to work with PostgreSQL JSONB data type.

- **Playbook**: [postgres_jsonb_test.yaml](../tests/fixtures/playbooks/data_transfer/postgres_jsonb_test/postgres_jsonb_test.yaml)

**Key Features:**
- Working with PostgreSQL JSONB data type
- Creating and using PostgreSQL functions
- Querying and filtering JSON data
- Updating JSON fields

### DuckDB Data Processing Example

This example demonstrates how to use DuckDB for data processing and analysis.

- **Playbook**: [duckdb_gcs_workload_identity.yaml](../tests/fixtures/playbooks/duckdb_gcs_workload_identity/duckdb_gcs_workload_identity.yaml)

**Key Features:**
- Loading data into DuckDB
- Data transformation and analysis
- Connecting to external data sources

## Cloud Integration Examples

### Google Cloud Storage OAuth Example

This example demonstrates how to use Google Cloud Storage with OAuth authentication.

- **Playbook**: [google_gcs_oauth.yaml](../tests/fixtures/playbooks/oauth/google_gcs/google_gcs_oauth.yaml)

**Key Features:**
- OAuth authentication for Google Cloud
- Accessing Google Cloud Storage
- Secure cloud storage operations

## Advanced Examples

### Multi-Playbook Batch Execution

This example demonstrates how to execute multiple playbooks in sequence.

- **Playbook**: [multi_playbook_batch.yaml](../tests/fixtures/playbooks/batch_execution/multi_playbook_batch/multi_playbook_batch.yaml)

**Key Features:**
- Calling multiple sub-playbooks
- Passing data between playbook executions
- Batch processing workflows

### Google Secret Manager Example

This example demonstrates how to work with Google Secret Manager.

- **Playbook**: [google_secret_manager.yaml](../tests/fixtures/playbooks/oauth/google_secret_manager/google_secret_manager.yaml)

**Key Features:**
- Retrieving secrets from Google Secret Manager
- Secure credential management
- Using secrets in workflows

## Integration Examples

### API Integration with AI

This example demonstrates AI-powered API integration using OpenAI to translate natural language queries into Amadeus flight search API calls.

- **Playbook**: [amadeus_ai_api.yaml](../tests/fixtures/playbooks/api_integration/amadeus_ai_api/amadeus_ai_api.yaml)

**Key Features:**
- AI-powered natural language to API translation
- Multi-step API orchestration
- Complex authentication flows
- Event tracking and logging

### GitHub API Metrics

This example demonstrates real-world API integration with GitHub API for repository analytics.

- **Playbook**: [github_metrics.yaml](../tests/fixtures/playbooks/api_integration/github_metrics/github_metrics.yaml)

**Key Features:**
- External API data fetching
- Data transformation and analysis
- Database storage and querying

### Wikipedia Data Processing

This example demonstrates complex data processing workflows with external APIs.

- **Playbook**: [wikipedia_processing.yaml](../tests/fixtures/playbooks/data_processing/wikipedia_processing/wikipedia_processing.yaml)

**Key Features:**
- API data fetching and processing
- Multi-database operations
- Data transformation pipelines



## Summary of Available Test Fixtures

| Category | Example | Playbook | Description |
|----------|---------|----------|-------------|
| **Basic** | Hello World | [hello_world.yaml](../tests/fixtures/playbooks/hello_world/hello_world.yaml) | Simple playbook execution |
| **Control Flow** | Weather Control Flow | [weather_control_flow.yaml](../tests/fixtures/playbooks/control_flow/weather_control_flow/weather_control_flow.yaml) | Conditional branching |
| **Database** | PostgreSQL JSONB | [postgres_jsonb_test.yaml](../tests/fixtures/playbooks/data_transfer/postgres_jsonb_test/postgres_jsonb_test.yaml) | JSONB operations |
| **Database** | DuckDB Processing | [duckdb_gcs_workload_identity.yaml](../tests/fixtures/playbooks/duckdb_gcs_workload_identity/duckdb_gcs_workload_identity.yaml) | DuckDB data processing |
| **API Integration** | Amadeus AI API | [amadeus_ai_api.yaml](../tests/fixtures/playbooks/api_integration/amadeus_ai_api/amadeus_ai_api.yaml) | AI-powered API translation |
| **API Integration** | GitHub Metrics | [github_metrics.yaml](../tests/fixtures/playbooks/api_integration/github_metrics/github_metrics.yaml) | GitHub API analytics |
| **Batch Execution** | Multi-Playbook Batch | [multi_playbook_batch.yaml](../tests/fixtures/playbooks/batch_execution/multi_playbook_batch/multi_playbook_batch.yaml) | Sub-playbook orchestration |
| **OAuth** | Google Secret Manager | [google_secret_manager.yaml](../tests/fixtures/playbooks/oauth/google_secret_manager/google_secret_manager.yaml) | Secret management |
| **OAuth** | Google GCS OAuth | [google_gcs_oauth.yaml](../tests/fixtures/playbooks/oauth/google_gcs/google_gcs_oauth.yaml) | Cloud storage with OAuth |
| **Data Processing** | Wikipedia Processing | [wikipedia_processing.yaml](../tests/fixtures/playbooks/data_processing/wikipedia_processing/wikipedia_processing.yaml) | Complex data pipelines |

## Next Steps

- [Playbook Structure](playbook_structure.md) - Learn how to structure NoETL playbooks
- [Workflow Tasks](action_type.md) - Learn about available tasks and their parameters
- [CLI Usage Guide](cli_usage.md) - Learn how to use the NoETL command-line interface
- [API Usage Guide](api_usage.md) - Learn how to use the NoETL REST API
