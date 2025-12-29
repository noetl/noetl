# Postgres → Excel → GCS Test

This test validates the complete data export pipeline using proper NoETL tools and handling distributed worker isolation through GCS intermediate storage.

## Architecture Pattern

**Key Design Principle**: Workers are stateless and may run on different machines. Local files created in one step won't be available in subsequent steps. Therefore, we use GCS as intermediate storage.

## Test Flow

1. **Create Temp Tables** (`start` step)
   - Tool: `postgres`
   - Creates 3 temporary PostgreSQL tables with sample data
   - Tables: `employees`, `products`, `orders`
   - 3 records per table

2. **Export to CSV via DuckDB** (`export_to_csv_gcs` step)
   - Tool: `duckdb` with postgres and httpfs extensions
   - Attaches to PostgreSQL database using auth credentials
   - Exports each temp table to CSV in GCS (`gs://.../temp/`)
   - Uses DuckDB's native GCS support (no direct postgres library usage)

3. **Create Excel from CSVs** (`create_excel_from_gcs_csv` step)
   - Tool: `python`
   - Downloads CSV files from GCS
   - Creates multi-sheet Excel workbook using xlsxwriter
   - Uploads final Excel to GCS (`gs://.../exports/`)
   - Cleans up temporary CSV files from GCS

4. **Complete** (`end` step)
   - Returns success status

## Prerequisites

- PostgreSQL connection: `pg_demo` credential
- GCS service account: `gcp_service_account` credential  
- GCS bucket: `noetl-test-exports` (must exist with write permissions)
- DuckDB extensions: `postgres`, `httpfs` (auto-installed by playbook)
- Python packages: `google-cloud-storage`, `xlsxwriter`

## Key Architecture Features

**No Direct Database Connections in Python**: Python code uses GCS client only, never connects directly to PostgreSQL. Data extraction is handled by DuckDB tool.

**Distributed Worker Isolation**: Each step may run on a different worker. GCS serves as the shared storage layer for intermediate files (CSVs) and final output (Excel).

**Credential Management**: Auth credentials are resolved by NoETL auth system and passed to tools (DuckDB, GCS) via the `auth:` configuration.

## Usage

### Register to Catalog
```bash
noetl catalog register tests/fixtures/playbooks/postgres_excel_gcs_test/postgres_excel_gcs_test.yaml
```

### Execute Test
```bash
noetl execute tests/postgres_excel_gcs
```

### Validate Results
Use the included Jupyter notebook `validate_results.ipynb` to:
- Check execution status and events
- Download and inspect Excel file from GCS
- Verify sheet contents match source tables

## Configuration

Workload variables (can be overridden at execution):
- `pg_auth`: PostgreSQL credential key (default: `pg_demo`)
- `gcs_auth`: GCS credential key (default: `gcp_service_account`)
- `gcs_bucket`: GCS bucket name (default: `noetl-test-exports`)
- `output_filename`: Excel filename without extension (default: `test_export`)

## Expected Output

```json
{
  "status": "completed",
  "message": "Successfully created Excel from postgres tables and uploaded to GCS"
}
```

Excel file structure:
- Sheet 1: **Employees** (emp_id, emp_name, department)
- Sheet 2: **Products** (product_id, product_name, price)
- Sheet 3: **Orders** (order_id, customer_name, order_date)

## Notes

- Temp tables are session-scoped and automatically cleaned up
- Excel file is created in `/tmp` and cleaned up after upload
- GCS path includes timestamp to avoid conflicts: `exports/{filename}.xlsx`
