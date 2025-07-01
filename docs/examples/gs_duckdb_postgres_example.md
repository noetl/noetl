# How to Run the GS DuckDB Postgres Example Playbook

This guide explains how to run the `gs_duckdb_postgres_example.yaml` playbook, which demonstrates a comprehensive ETL workflow using Google Storage, DuckDB, and PostgreSQL with secure secret management.

## Workflow Overview

This playbook demonstrates a complete data pipeline that:
1. Retrieves secrets from Google Secret Manager
2. Tests connections to Google Cloud Storage by creating and uploading a test file
3. Reads data from PostgreSQL
4. Processes and transforms data using DuckDB
5. Stores data in multiple formats and locations
6. Cleans up secrets after execution

## Workflow Execution Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            NOETL WORKFLOW EXECUTION                              │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   START     │───▶│ Get Secrets      │───▶│ Create Secrets  │───▶│ Test GCS        │
│             │    │ from GSM         │    │ in DuckDB       │    │ Credentials     │
└─────────────┘    └──────────────────┘    └─────────────────┘    └─────────────────┘
                             │                        │                        │
                             ▼                        ▼                        ▼
                   ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
                   │ • GCS Key ID     │    │ • GCS Secret    │    │ • Create test   │
                   │ • GCS Secret Key │    │ • PG Secret     │    │   file & upload │
                   │ • PG User        │    │   (with exec_id)│    │ • Read back     │
                   │ • PG Password    │    │                 │    │ • Verify access │
                   └──────────────────┘    └─────────────────┘    └─────────────────┘

┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ Read from       │───▶│ Upload CSV       │───▶│ Download &      │───▶│ Create PG       │
│ PostgreSQL      │    │ to GS            │    │ Convert         │    │ Table           │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └─────────────────┘
         │                        │                        │                        │
         ▼                        ▼                        ▼                        ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ PostgreSQL      │    │ Google Storage   │    │ Local FS        │    │ PostgreSQL      │
│ test_data_table │    │ /uploads/        │    │ /tmp/           │    │ test_data       │
│                 │    │ test_data.csv    │    │ test_data.csv   │    │ (new table)     │
│ ├─ Read data    │    │                  │    │ test_data.pqt   │    │                 │
│ ├─ Save to CSV  │    │ ├─ Upload CSV    │    │                 │    │ ├─ CREATE TABLE │
│                 │    │                  │    │ ├─ Download CSV │    │                 │
└─────────────────┘    └──────────────────┘    │ ├─ Convert to   │    └─────────────────┘
                                               │   Parquet       │
                                               └─────────────────┘

┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ Load Data       │───▶│ Upload Parquet   │───▶│ Advanced File   │───▶│ Delete Secrets  │
│ to PostgreSQL   │    │ to GS            │    │ Operations      │    │ & Cleanup       │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └─────────────────┘
         │                        │                        │                        │
         ▼                        ▼                        ▼                        ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ PostgreSQL      │    │ Google Storage   │    │ Multiple Demos  │    │ DuckDB Secrets  │
│ test_data       │    │ /uploads/        │    │                 │    │ & Temp Files    │
│                 │    │ test_data.pqt    │    │ ├─ Multi-file   │    │                 │
│ ├─ INSERT data  │    │                  │    │   reading       │    │ ├─ DROP SECRET  │
│   from Parquet  │    │ ├─ Upload        │    │ ├─ Compressed   │    │   gcs_access    │
│ ├─ Type casting │    │   Parquet        │    │   files         │    │ ├─ Note: PG     │
│ ├─ NULL handling│    │                  │    │ ├─ Glob patterns│    │   secret file   │
│                 │    │                  │    │                 │    │   remains       │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └─────────────────┘

                                   ┌─────────────────┐
                                   │       END       │
                                   │   Workflow      │
                                   │   Complete      │
                                   └─────────────────┘
```

## System Connections and Data Flows

### 1. Secret Management Flow
```
Google Secret Manager ──→ NoETL Workflow ──→ DuckDB Secrets
├─ GCS HMAC Key ID          ├─ Retrieve secrets    ├─ CREATE SECRET gcs_access
├─ GCS HMAC Secret Key      ├─ Pass to workbook    ├─ Store PG credentials in CSV
├─ PostgreSQL User          └─ Create DuckDB       └─ Execution-specific naming
└─ PostgreSQL Password        secrets with exec_id
```

### 2. Database Connections
```
PostgreSQL Database (Source)
├─ Host: localhost:5434 (default)
├─ Database: noetl
├─ Table: test_data_table
├─ Authentication: Secret-based
└─ Operations:
    ├─ READ: Extract data to CSV
    └─ WRITE: Create new table, INSERT data

DuckDB (Processing Engine)
├─ Extensions: postgres, httpfs, parquet
├─ Secrets: gcs_access, pg_credentials
├─ Temporary tables for processing
└─ Direct file operations (CSV, Parquet)
```

### 3. Storage Connections
```
Google Cloud Storage
├─ Bucket: noetl-demo-19700101
├─ Authentication: HMAC keys (S3-compatible)
├─ Endpoint: storage.googleapis.com
├─ Files:
│   ├─ test_connection.csv (credentials test file)
│   ├─ uploads/test_data.csv
│   └─ uploads/test_data.parquet
└─ Operations: Upload, Download, Read

Local File System
├─ Source: data/test/test_data.csv
├─ Temporary files:
│   ├─ /tmp/test_data.csv
│   ├─ /tmp/test_data.parquet
│   ├─ /tmp/pg_secret_{exec_id}.csv (remains after execution)
│   ├─ /tmp/sample1.csv, /tmp/sample2.csv
│   ├─ /tmp/sample_compressed.csv.gz
│   └─ /tmp/advanced_test.csv
└─ Operations: Read, Write, Convert
```

## Detailed Workflow Steps

### Phase 1: Authentication Setup
1. **Get Secrets** - Retrieve 4 secrets from Google Secret Manager:
   - GCS HMAC Key ID
   - GCS HMAC Secret Key  
   - PostgreSQL Username
   - PostgreSQL Password

2. **Create DuckDB Secrets**:
   - **GCS Secret**: Creates persistent S3-compatible secret for Google Storage
   - **PG Secret**: Stores PostgreSQL credentials in CSV file with execution ID

3. **Test Connections**: Validates GCS access by creating, uploading, and reading back a test file

### Phase 2: Data Extraction and Upload
4. **Read from PostgreSQL**:
   - Connects to PostgreSQL using secret-based authentication
   - Reads from `test_data_table`
   - Saves data to local CSV file (`/tmp/test_data.csv`)

5. **Upload CSV to Google Storage**:
   - Reads local CSV with auto-detection
   - Uploads to `gs://bucket/uploads/test_data.csv`

### Phase 3: Data Transformation
6. **Download and Convert**:
   - Downloads CSV from Google Storage
   - Converts to Parquet format with ZSTD compression
   - Saves locally as `/tmp/test_data.parquet`

### Phase 4: Database Loading
7. **Create PostgreSQL Table**:
   - Uses direct authentication (alternative to secrets)
   - Creates `test_data` table with proper schema
   - Demonstrates different authentication methods

8. **Load Data to PostgreSQL**:
   - Reads Parquet file into DuckDB
   - Performs type casting and NULL handling
   - Inserts data into PostgreSQL table

### Phase 5: Advanced Operations
9. **Upload Parquet to Google Storage**:
   - Demonstrates multiple file operations:
     - Reading multiple files as array
     - Reading compressed files
     - Using glob patterns
   - Uploads final Parquet to Google Storage

10. **Advanced File Operations**:
    - Creates sample data for demonstrations
    - Shows various DuckDB file handling capabilities
    - Tests auto-detection features

### Phase 6: Cleanup
11. **Delete Secrets**:
    - Drops DuckDB secrets
    - **Note**: Temporary PostgreSQL credentials file `/tmp/pg_secret_{execution_id}.csv` remains on the filesystem due to DuckDB limitations

## Prerequisites

### Environment Setup
```bash
# Required environment variables
export GOOGLE_CLOUD_PROJECT="your-project-id"
export POSTGRES_HOST="localhost"
export POSTGRES_PORT="5434"
export POSTGRES_USER="noetl"
export POSTGRES_PASSWORD="noetl"
export POSTGRES_DB="noetl"

# Secret names in Google Secret Manager
export GCS_KEY_ID_SECRET="s3_access_key_id"
export GCS_SECRET_KEY_SECRET="s3_secret_access_key"
export POSTGRES_USER_SECRET="postgres_user"
export POSTGRES_PASSWORD_SECRET="postgres_password"
```

### Required Secrets in Google Secret Manager
1. **s3_access_key_id**: GCS HMAC access key ID
2. **s3_secret_access_key**: GCS HMAC secret access key
3. **postgres_user**: PostgreSQL username
4. **postgres_password**: PostgreSQL password

### Required Infrastructure
1. **PostgreSQL Database** with `test_data_table` containing sample data
2. **Google Cloud Storage** bucket with read/write permissions
3. **Google Secret Manager** with stored credentials
4. **NoETL** server running with proper Google Cloud authentication

## Running the Playbook

### 1. Register the Playbook
```bash
noetl playbook --register playbook/gs_duckdb_postgres_example.yaml --port 8080
```

### 2. Execute the Workflow
```bash
noetl playbook --execute --path "workflows/examples/gs_duckdb_postgres_example" --port 8080 --payload '{
  "GOOGLE_CLOUD_PROJECT": "noetl-demo-19700101",
  "GCS_KEY_ID_SECRET": "s3_access_key_id",
  "GCS_SECRET_KEY_SECRET": "s3_secret_access_key",
  "POSTGRES_HOST": "db",
  "POSTGRES_PORT": "5432",
  "POSTGRES_USER": "noetl",
  "POSTGRES_PASSWORD": "noetl",
  "POSTGRES_DB": "noetl"
}'
```

### 3. Monitor Execution
The workflow will create a unique execution ID and use it throughout the process for:
- Naming temporary secret files
- Tracking workflow progress
- Ensuring cleanup of resources

## Key Features Demonstrated

### Security Features
- **Secret Management**: Secure retrieval from Google Secret Manager
- **Execution Isolation**: Unique execution IDs for concurrent runs
- **Multiple Auth Methods**: Both secret-based and direct authentication
- **Credential Cleanup**: Automatic cleanup of temporary credentials

### DuckDB Capabilities
- **Multi-format Support**: CSV, Parquet, JSON handling
- **Cloud Integration**: Native Google Storage integration via S3 protocol
- **Database Connectivity**: Direct PostgreSQL integration
- **Advanced File Operations**: Glob patterns, compression, multi-file reading
- **Type System**: Automatic type detection and conversion
- **Performance**: Parallel processing and optimized formats

### Data Pipeline Features
- **ETL Operations**: Extract, Transform, Load with multiple systems
- **Format Conversion**: Seamless conversion between CSV and Parquet
- **Compression**: ZSTD compression for efficient storage
- **Schema Management**: Automatic schema detection and table creation
- **Error Handling**: Robust NULL handling and type conversion

## Troubleshooting

### Common Issues
1. **Secret Access**: Ensure Google Cloud authentication is configured
2. **PostgreSQL Connection**: Verify database is running and accessible
3. **GCS Permissions**: Check bucket permissions and HMAC key validity
4. **File Paths**: Ensure source data file exists at specified location

### Debug Steps
1. Check NoETL server logs for execution details
2. Verify secret values in Google Secret Manager
3. Test database connectivity manually
4. Validate GCS bucket access with gsutil or similar tools
