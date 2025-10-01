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

### Static Tests (Default)
```bash
make test-http-duckdb-postgres
```
Tests playbook parsing, planning, and structural validation without runtime execution.

### Runtime Tests (Optional)
Requires:
- PostgreSQL connection (`pg_local` credential)
- GCS access (`gcs_hmac_local` credential)  
- Internet connectivity for weather API

```bash
# With running server and credentials configured
make test-http-duckdb-postgres-runtime

# Full integration (reset DB, restart server, run tests)
make test-http-duckdb-postgres-full
```

## Configuration

The playbook expects these authentication credentials:
- `pg_local`: PostgreSQL database connection
- `gcs_hmac_local`: GCS HMAC credentials for bucket access

Workload parameters:
- `cities`: List of cities with lat/lon coordinates
- `base_url`: Weather API endpoint
- `gcs_bucket`: Target GCS bucket for output files