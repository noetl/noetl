# How to Run the GS Duckdb Postgres Example Playbook

This guide explains how to run the `gs_duckdb_postgres_example.yaml` playbook, which demonstrates file operations with Google Storage, DuckDB, and PostgreSQL.

## What This Playbook Does

The playbook demonstrates DuckDB's native file handling capabilities:
- Reading CSV files directly from the local filesystem
- Uploading files to Google Storage using DuckDB
- Reading files from Google Storage
- Converting between file formats CSV to Parquet
- Reading multiple files using list parameters
- Reading compressed files
- Using glob patterns to read multiple files
- Creating tables in Postgres and loading data
- Auto-detecting CSV format with read_csv_auto
- Specifying CSV options
- Handling NULL values and type conversion
- Parallel CSV reading for performance

## Prerequisites

1. NoETL installed and configured
2. Google Cloud SDK installed and configured
3. HMAC keys for Google Cloud Storage already created and stored in Google Secret Manager
4. Postgres database accessible with the credentials you'll provide
5. Permissions in Google Cloud project:
   - Secret Manager Secret Accessor (`roles/secretmanager.secretAccessor`) for accessing secrets
   - Storage Object Admin (`roles/storage.objectAdmin`) for accessing Google Cloud Storage

## Method 1: Using Environment Variables with the Agent Command

This method uses environment variables loaded from `.env.examples` files and runs the playbook using the `noetl agent` command.

### Step 1: Set up your environment variables

Create or update your `.env.examples` file with the following variables:

```bash
GOOGLE_CLOUD_PROJECT="google-project-id"
GOOGLE_APPLICATION_CREDENTIALS=".secrets/credentials.json"
GCS_KEY_ID_SECRET="s3_access_key_id"
GCS_SECRET_KEY_SECRET="s3_secret_access_key"
POSTGRES_HOST="localhost"
POSTGRES_PORT="5434"
POSTGRES_USER="noetl"
POSTGRES_PASSWORD="noetl"
POSTGRES_DB="noetl"
```

### Step 2: Load the environment variables and run the playbook

```bash
source bin/load_env_files.sh dev
noetl agent -f playbook/gs_duckdb_postgres_example.yaml
```

Alternatively, use a one-line:

```bash
set -a; source .env.example; noetl agent -f playbook/gs_duckdb_postgres_example.yaml
```

### Step 3: Verify the results

Check the output of the command to verify that:
1. The HMAC keys were successfully retrieved from Google Secret Manager
2. A DuckDB secret was created for GCS authentication
3. The CSV file was successfully uploaded to Google Cloud Storage
4. The CSV file was downloaded and converted to Parquet
5. The table was created in PostgreSQL
6. The data was loaded into PostgreSQL
7. The Parquet file was uploaded to Google Cloud Storage
8. The advanced file operations were demonstrated successfully

## Method 2: Using the Playbook Command with a Payload

This method uses the `noetl playbook` command with a JSON payload to provide the necessary parameters.

### Step 1: Register the playbook

```bash
noetl playbook --register playbook/gs_duckdb_postgres_example.yaml --port 8080
```

### Step 2: Execute the playbook with a payload

```bash
noetl playbook --execute --path "workflows/examples/gs_duckdb_postgres_example" --payload '{
  "GOOGLE_CLOUD_PROJECT": "noetl-demo-19700101",
  "GCS_KEY_ID_SECRET": "s3_access_key_id",
  "GCS_SECRET_KEY_SECRET": "s3_secret_access_key",
  "POSTGRES_HOST": "localhost",
  "POSTGRES_PORT": "5434",
  "POSTGRES_USER": "noetl",
  "POSTGRES_PASSWORD": "noetl",
  "POSTGRES_DB": "noetl"
}'
```

### Step 3: Verify the results

Check the output of the command to verify that the operation was successful.

## Workflow Explanation

When you run the playbook, it performs the following steps:

1. Retrieves the HMAC key ID from Google Secret Manager
2. Retrieves the HMAC secret key from Google Secret Manager
3. Creates a DuckDB secret for GCS authentication
4. Uploads a CSV file to Google Cloud Storage
5. Downloads the CSV file from Google Cloud Storage and converts it to Parquet
6. Creates a table in PostgreSQL
7. Loads data from the Parquet file into PostgreSQL
8. Uploads the Parquet file to Google Cloud Storage
9. Demonstrates advanced file operations with DuckDB

## Troubleshooting

If you encounter issues running the playbook, check the following:

1. Ensure your Google Cloud credentials are valid and have the necessary permissions
2. Verify that the secrets exist in Google Secret Manager and you have permission to access them
3. Check that the environment variables or payload parameters are correctly set
4. Ensure the source CSV file exists at the specified path
5. Verify that your PostgreSQL database is accessible with the provided credentials
6. Look for error messages in the output that might indicate specific issues

## Next Steps

After successfully running this playbook, you can:

1. Verify the uploaded files in Google Cloud Storage
2. Check the data in your PostgreSQL database
3. Modify the playbook to work with your own files and databases
4. Integrate this pattern into your own playbooks