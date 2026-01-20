---
sidebar_position: 7
title: GCS Tool
description: Upload files to Google Cloud Storage
---

# GCS Tool

The GCS tool uploads files to Google Cloud Storage buckets using service account authentication.

## Basic Usage

```yaml
- step: upload_file
  tool: gcs
  source: "/tmp/output.csv"
  destination: "gs://my-bucket/data/output.csv"
  credential: gcp_service_account
  next:
    - step: notify_complete
```

## Configuration

### Required Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `source` | string | Local file path to upload |
| `destination` | string | GCS URI (gs://bucket/path) |
| `credential` | string | Name of GCS service account credential |

### Optional Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `content_type` | string | auto-detect | MIME type of the file |
| `metadata` | object | `{}` | Custom metadata key-value pairs |

## Authentication

The GCS tool requires a service account credential with the following structure:

```json
{
  "type": "gcs",
  "service_account_json": {
    "type": "service_account",
    "project_id": "my-project",
    "private_key_id": "...",
    "private_key": "-----BEGIN PRIVATE KEY-----\n...",
    "client_email": "my-sa@my-project.iam.gserviceaccount.com",
    "client_id": "...",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token"
  }
}
```

Register the credential:

```bash
noetl register credential gcp_service_account.yaml
```

## Response Format

```json
{
  "status": "success",
  "uri": "gs://my-bucket/data/output.csv",
  "bucket": "my-bucket",
  "blob": "data/output.csv",
  "size": 12345,
  "content_type": "text/csv",
  "message": "Uploaded 12345 bytes to GCS"
}
```

## Examples

### Simple File Upload

```yaml
- step: upload_report
  tool: gcs
  source: "/tmp/daily_report.pdf"
  destination: "gs://reports-bucket/daily/{{ workload.date }}/report.pdf"
  credential: gcp_service_account
  content_type: "application/pdf"
```

### Upload with Metadata

```yaml
- step: upload_with_metadata
  tool: gcs
  source: "/tmp/processed_data.parquet"
  destination: "gs://data-lake/processed/{{ execution_id }}/data.parquet"
  credential: gcp_service_account
  content_type: "application/octet-stream"
  metadata:
    execution_id: "{{ execution_id }}"
    processed_at: "{{ workload.timestamp }}"
    source_system: "noetl"
```

### Dynamic Destination

```yaml
- step: upload_dynamic
  tool: gcs
  source: "{{ vars.local_file_path }}"
  destination: "gs://{{ workload.bucket }}/{{ workload.prefix }}/{{ vars.filename }}"
  credential: "{{ workload.gcs_credential }}"
```

### Pipeline Integration

```yaml
workflow:
  - step: start
    next:
      - step: generate_data

  - step: generate_data
    tool: python
    code: |
      import json
      def main(records):
          output_path = "/tmp/output.json"
          with open(output_path, 'w') as f:
              json.dump(records, f)
          return {"file_path": output_path, "record_count": len(records)}
    args:
      records: "{{ workload.data }}"
    vars:
      output_file: "{{ result.data.file_path }}"
    next:
      - step: upload_to_gcs

  - step: upload_to_gcs
    tool: gcs
    source: "{{ vars.output_file }}"
    destination: "gs://data-exports/{{ execution_id }}/data.json"
    credential: gcp_service_account
    content_type: "application/json"
    vars:
      gcs_uri: "{{ result.uri }}"
    next:
      - step: notify

  - step: notify
    tool: http
    method: POST
    endpoint: "{{ workload.webhook_url }}"
    payload:
      status: "complete"
      uri: "{{ vars.gcs_uri }}"
    next:
      - step: end

  - step: end
```

## Error Handling

```yaml
- step: upload_file
  tool: gcs
  source: "/tmp/data.csv"
  destination: "gs://my-bucket/data.csv"
  credential: gcp_service_account
  next:
    - when: "{{ upload_file.status == 'error' }}"
      then:
        - step: handle_upload_error
    - step: continue_workflow

- step: handle_upload_error
  tool: python
  code: |
    def main(error_message):
        return {"action": "retry", "error": error_message}
  args:
    error_message: "{{ upload_file.error }}"
```

## Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `Credential not found` | Invalid credential name | Check credential registration |
| `Permission denied` | Insufficient IAM permissions | Grant `storage.objects.create` |
| `Bucket not found` | Invalid bucket name | Verify bucket exists |
| `File not found` | Source file missing | Check source path |

## Required IAM Permissions

The service account needs these permissions:

- `storage.objects.create` - Create objects
- `storage.objects.get` - Read objects (for metadata updates)

Or use the predefined role: `roles/storage.objectCreator`

## Best Practices

1. **Use specific paths**: Include execution_id or timestamps in paths
2. **Set content types**: Explicitly set MIME types for clarity
3. **Add metadata**: Include tracking information in metadata
4. **Handle errors**: Always check upload status before proceeding
5. **Clean up temp files**: Remove local files after successful upload

## Alternatives

For reading from GCS or complex cloud operations, consider:

- **DuckDB tool**: Read/write Parquet files directly from GCS
- **Python tool**: Full control with google-cloud-storage SDK
- **Container tool**: Complex GCS operations with gcloud CLI

## See Also

- [DuckDB Tool](/docs/reference/tools/duckdb) - Analytics with GCS data
- [Python Tool](/docs/reference/tools/python) - Custom GCS operations
- [Authentication Reference](/docs/reference/auth_and_keychain_reference)
