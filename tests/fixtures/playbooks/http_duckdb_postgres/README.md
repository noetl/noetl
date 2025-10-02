# http_duckdb_postgres

A comprehensive integration test demonstrating:
- **HTTP API integration** with external weather service (Open-Meteo)
- **Async iterator processing** over multiple cities
- **PostgreSQL storage** with upsert capabilities
- **DuckDB analytics** with cross-database queries
- **GCS cloud storage** output using unified authentication
- **Multi-stage pipeline** with data transformation and aggregation

## Pipeline Flow

1. **Setup**: Creates PostgreSQL table for raw HTTP results
2. **Data Collection**: Fetches weather data for multiple cities (London, Paris, Berlin) asynchronously
3. **Storage**: Saves raw HTTP responses to PostgreSQL with upsert mode
4. **Analytics**: Uses DuckDB to:
   - Connect to PostgreSQL data
   - Flatten and aggregate results by city
   - Export processed data to GCS as Parquet files
5. **Metrics**: Records pipeline metrics back to PostgreSQL

## Key Features Tested

- **Iterator step type** with async mode for parallel processing
- **Cross-database connectivity** (DuckDB → PostgreSQL)
- **Cloud storage integration** with credential management
- **Data format handling** (JSON → SQL → Parquet)
- **Error handling** with safe defaults in Jinja expressions
- **Unified authentication** across multiple services

## Testing

### Static Tests
For static parsing and validation without runtime execution, use pytest:
```bash
pytest tests/ -k http_duckdb_postgres
```
Tests playbook parsing, planning, and structural validation without runtime execution.

### Runtime Tests with Kubernetes Cluster

#### Prerequisites
- Kubernetes cluster deployed with NoETL (use `task bring-all` to deploy full stack)
- NoETL API accessible on `localhost:8082`
- PostgreSQL accessible on `localhost:54321`
- Internet connectivity for weather API

#### Test Commands
```bash
# Register required credentials
task register-test-credentials

# Register HTTP DuckDB Postgres playbook
task test-register-http-duckdb-postgres

# Execute HTTP DuckDB Postgres test
task test-execute-http-duckdb-postgres

# Full integration test (credentials + register + execute)
task test-http-duckdb-postgres-full
```

#### Alias Commands (shorter)
```bash
# Register credentials
task rtc

# Register playbook
task trhdp

# Execute playbook
task tehdp

# Full test workflow
task thdpf
```

## Configuration

The playbook expects these authentication credentials:
- `pg_k8s`: PostgreSQL database connection (for cluster-based testing)
- `gcs_hmac_local`: GCS HMAC credentials for bucket access

Workload parameters:
- `cities`: List of cities with lat/lon coordinates
- `base_url`: Weather API endpoint
- `gcs_bucket`: Target GCS bucket for output files