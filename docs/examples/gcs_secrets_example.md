# GCS Secrets Example Playbook Documentation

## Overview
The `gcs_secrets_example.yaml` playbook demonstrates Google Cloud Storage (GCS) authentication using secrets management. It showcases how to securely retrieve GCS HMAC credentials from Google Secret Manager and use them for GCS operations within DuckDB.

## Playbook Details
- **API Version**: noetl.io/v1
- **Kind**: Playbook
- **Name**: gcs_secrets_example
- **Path**: workflows/examples/gcs_secrets_example

## Purpose
This playbook demonstrates:
- Retrieving GCS HMAC credentials from Google Secret Manager
- Creating a DuckDB secret for GCS authentication using the CREATE SECRET syntax
- Using this secret for GCS operations
- Secure handling of cloud storage credentials
- CSV file upload to Google Cloud Storage

## Workload Configuration

### Environment Variables
The playbook uses the following environment variables with default fallbacks:

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_CLOUD_PROJECT` | noetl-demo-19700101 | Google Cloud Project ID |
| `GCS_KEY_ID_SECRET` | gcs-key-id | Secret Manager secret name for GCS Key ID |
| `GCS_SECRET_KEY_SECRET` | gcs-secret-key | Secret Manager secret name for GCS Secret Key |

### Additional Configuration
- **Job ID**: Generated using `{{ job.uuid }}`
- **GS Bucket**: noetl-demo-19700101
- **Source CSV Path**: data/test/test_data.csv
- **GS CSV Path**: uploads/test_data.csv

## Workflow Steps

### 1. Start Step
- **Description**: Start GCS Secrets Example Workflow
- **Next**: get_gcs_key_id

### 2. Get GCS Key ID Step
- **Description**: Retrieve GCS HMAC Key ID from Google Secret Manager
- **Type**: secrets
- **Provider**: google
- **Secret Name**: `{{ workload.gcs_key_id_secret }}`
- **Next**: get_gcs_secret_key

### 3. Get GCS Secret Key Step
- **Description**: Retrieve GCS HMAC Secret Key from Google Secret Manager
- **Type**: secrets
- **Provider**: google
- **Secret Name**: `{{ workload.gcs_secret_key_secret }}`
- **Next**: create_gcs_secret

### 4. Create GCS Secret Step
- **Description**: Create DuckDB secret for GCS authentication
- **Type**: workbook
- **Workbook**: create_gcs_secret_task
- **Parameters**: 
  - key_id: Retrieved from Secret Manager
  - secret_key: Retrieved from Secret Manager
- **Next**: upload_csv_to_gs

### 5. Upload CSV to GS Step
- **Description**: Upload CSV file to Google Storage bucket using the created secret
- **Type**: workbook
- **Workbook**: upload_csv_task
- **Next**: end

### 6. End Step
- **Description**: End of workflow

## Workbook Tasks

### Create GCS Secret Task (`create_gcs_secret_task`)

#### Purpose
Creates a DuckDB secret for GCS authentication using retrieved HMAC credentials.

#### Operations
1. **Extension Management**:
   ```sql
   INSTALL httpfs;
   LOAD httpfs;
   ```

2. **Secret Creation**:
   ```sql
   CREATE OR REPLACE SECRET gcs_secret (
       TYPE S3,
       KEY_ID '{{ key_id }}',
       SECRET '{{ secret_key }}'
   );
   ```

3. **GCS Configuration**:
   ```sql
   SET s3_endpoint='storage.googleapis.com';
   SET s3_region='auto';
   SET s3_url_style='path';
   ```

4. **Verification**:
   Returns success message confirming secret creation

### Upload CSV Task (`upload_csv_task`)

#### Purpose
Reads a local CSV file and uploads it to Google Cloud Storage using the created secret.

#### Operations
1. **Extension Management**:
   ```sql
   INSTALL httpfs;
   LOAD httpfs;
   ```

2. **GCS Configuration**:
   ```sql
   SET s3_endpoint='storage.googleapis.com';
   SET s3_region='auto';
   SET s3_url_style='path';
   ```

3. **CSV Processing**:
   ```sql
   CREATE TABLE temp_csv AS 
   SELECT * FROM read_csv_auto('{{ workload.source_csv_path }}', 
                              all_varchar=false,  
                              sample_size=-1);
   ```
   - `all_varchar=false`: Attempts to detect column types automatically
   - `sample_size=-1`: Uses all rows for type detection

4. **Data Inspection**:
   ```sql
   SELECT * FROM temp_csv;
   DESCRIBE temp_csv;
   ```

5. **Upload to GCS**:
   ```sql
   COPY temp_csv TO 'gs://{{ workload.gs_bucket }}/{{ workload.gs_csv_path }}' (FORMAT CSV, HEADER);
   ```

6. **Cleanup**:
   ```sql
   DROP TABLE temp_csv;
   ```

## Prerequisites

### Google Cloud Setup
1. **Google Cloud Project**: Active GCP project with billing enabled
2. **Secret Manager API**: Enabled in your GCP project
3. **Storage API**: Enabled in your GCP project
4. **Service Account**: With appropriate permissions for Secret Manager and Storage

### Required Permissions
- `secretmanager.versions.access` for Secret Manager
- `storage.objects.create` for GCS uploads
- `storage.buckets.get` for bucket access

### GCS HMAC Keys
1. **Generate HMAC Keys**: Create HMAC access keys for your service account
2. **Store in Secret Manager**: 
   - Store Key ID in secret named by `GCS_KEY_ID_SECRET`
   - Store Secret Key in secret named by `GCS_SECRET_KEY_SECRET`

### Local Setup
1. **Authentication**: Set up Google Cloud authentication (service account key or ADC)
2. **CSV File**: Ensure source CSV file exists at the specified path
3. **DuckDB Extensions**: httpfs extension must be available

## Usage

### Running the Playbook
```bash
noetl playbook --register playbook/gcs_secrets_example.yaml --port 8080
noetl playbook --execute --path "workflows/examples/gcs_secrets_example" --payload '{"GOOGLE_CLOUD_PROJECT": "your-project-id"}'
```

### Environment Variables Setup
```bash
export GOOGLE_CLOUD_PROJECT=your-project-id
export GCS_KEY_ID_SECRET=gcs-key-id
export GCS_SECRET_KEY_SECRET=gcs-secret-key
```

### Payload Example
```json
{
  "GOOGLE_CLOUD_PROJECT": "your-project-id"
}
```

## Security Considerations

### Best Practices
1. **Secret Rotation**: Regularly rotate HMAC keys
2. **Least Privilege**: Grant minimal required permissions
3. **Environment Isolation**: Use different secrets for different environments
4. **Audit Logging**: Enable Cloud Audit Logs for secret access

### Secret Management
- Never hardcode credentials in playbooks
- Use Secret Manager for sensitive data
- Implement proper IAM policies
- Monitor secret access patterns

## Expected Outcomes

### Successful Execution
1. HMAC credentials successfully retrieved from Secret Manager
2. DuckDB secret created with GCS authentication
3. Local CSV file processed and analyzed
4. File successfully uploaded to specified GCS bucket
5. Temporary tables cleaned up

### Verification
After execution, verify:
- File exists in GCS bucket at the specified path
- File contains expected data with proper formatting
- No temporary tables remain in DuckDB session
- Cloud Audit Logs show successful secret access

## Troubleshooting

### Common Issues

#### Authentication Errors
- **Symptom**: "Permission denied" or "Unauthorized"
- **Solution**: Verify service account permissions and authentication setup

#### Secret Access Errors
- **Symptom**: "Secret not found" or "Access denied"
- **Solution**: Check secret names and IAM permissions for Secret Manager

#### GCS Upload Errors
- **Symptom**: "Bucket not found" or "Upload failed"
- **Solution**: Verify bucket exists and HMAC credentials are valid

#### File Not Found Errors
- **Symptom**: "CSV file not found"
- **Solution**: Ensure source CSV file exists at specified path

### Debug Steps
1. **Verify Authentication**: Test Google Cloud authentication
2. **Check Secrets**: Manually verify secrets exist in Secret Manager
3. **Test Bucket Access**: Verify bucket exists and is accessible
4. **Validate CSV**: Ensure source CSV file is readable and properly formatted

## Related Files
- Base playbook: `playbook/gcs_secrets_example.yaml`
- Authentication guide: `playbook/GCS_AUTHENTICATION_README.md`
- Setup instructions: `playbook/HOW_TO_RUN_GCS_SECRETS.md`
- Service account creation: `playbook/create_service_account.py`
- HMAC key generation: `playbook/generate_gcs_hmac_keys.yaml`

## Advanced Usage

### Custom CSV Processing
Modify the `read_csv_auto` parameters for specific CSV formats:
```sql
-- For custom delimiter
SELECT * FROM read_csv_auto('file.csv', delim=';')

-- For specific column types
SELECT * FROM read_csv('file.csv', columns={'id': 'INTEGER', 'name': 'VARCHAR'})
```

### Multiple File Upload
Extend the workbook to handle multiple files:
```sql
-- Upload multiple files
COPY (SELECT * FROM read_csv_auto('file1.csv')) TO 'gs://bucket/file1.csv' (FORMAT CSV, HEADER);
COPY (SELECT * FROM read_csv_auto('file2.csv')) TO 'gs://bucket/file2.csv' (FORMAT CSV, HEADER);
```