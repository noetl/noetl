"""
GCS task executor for uploading files to Google Cloud Storage.

This module provides functionality to upload files to GCS buckets using
service account authentication.
"""

import json
import os
from typing import Dict, Any, Optional, Callable
from pathlib import Path

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def execute_gcs_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Any,
    task_with: Dict[str, Any],
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a GCS file upload task.
    
    Args:
        task_config: Task configuration containing:
            - source: Local file path to upload
            - destination: GCS URI (gs://bucket-name/path/to/file)
            - credential: Name of GCS service account credential
            - content_type: Optional MIME type
            - metadata: Optional dict of metadata key-value pairs
        context: Execution context
        jinja_env: Jinja2 environment for templating
        task_with: Additional task parameters
        log_event_callback: Optional callback for logging events
        
    Returns:
        Dict with upload result containing:
            - status: 'success' or 'error'
            - uri: GCS URI of uploaded file
            - size: File size in bytes
            - content_type: MIME type
    """
    from google.cloud import storage
    from google.oauth2 import service_account
    import tempfile
    
    task_id = task_config.get('task_id', 'gcs_upload')
    task_name = task_config.get('name', 'gcs_upload')
    
    logger.info(f"GCS TASK: Starting upload task {task_id}")
    
    # Extract task parameters
    source_path = task_config.get('source') or task_with.get('source')
    destination_uri = task_config.get('destination') or task_with.get('destination')
    credential_name = task_config.get('credential') or task_with.get('credential')
    content_type = task_config.get('content_type') or task_with.get('content_type')
    metadata = task_config.get('metadata') or task_with.get('metadata') or {}
    
    if not source_path:
        raise ValueError("GCS upload requires 'source' parameter (local file path)")
    
    if not destination_uri:
        raise ValueError("GCS upload requires 'destination' parameter (gs://bucket/path)")
    
    if not credential_name:
        raise ValueError("GCS upload requires 'credential' parameter (service account credential name)")
    
    # Parse GCS URI
    if not destination_uri.startswith('gs://'):
        raise ValueError(f"Destination must be a GCS URI starting with gs://, got: {destination_uri}")
    
    uri_parts = destination_uri[5:].split('/', 1)
    bucket_name = uri_parts[0]
    blob_name = uri_parts[1] if len(uri_parts) > 1 else ''
    
    if not blob_name:
        # If no blob name, use source filename
        blob_name = Path(source_path).name
    
    logger.info(f"GCS UPLOAD: {source_path} -> gs://{bucket_name}/{blob_name}")
    
    # Fetch credential from NoETL server
    try:
        credential_data = _fetch_credential(credential_name)
        if not credential_data:
            raise ValueError(f"Credential '{credential_name}' not found")
        
        # Extract service account JSON
        sa_json = credential_data.get('service_account_json')
        if not sa_json:
            raise ValueError(f"Credential '{credential_name}' missing 'service_account_json' field")
        
        # If sa_json is already a dict, use it; if it's a string, parse it
        if isinstance(sa_json, str):
            sa_json = json.loads(sa_json)
        
        # Create credentials from service account info
        credentials = service_account.Credentials.from_service_account_info(sa_json)
        
        # Create GCS client
        client = storage.Client(credentials=credentials, project=sa_json.get('project_id'))
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        
        # Check if source file exists
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Source file not found: {source_path}")
        
        # Get file size
        file_size = os.path.getsize(source_path)
        
        # Upload file
        logger.info(f"Uploading {file_size} bytes to gs://{bucket_name}/{blob_name}")
        
        upload_kwargs = {}
        if content_type:
            upload_kwargs['content_type'] = content_type
        
        blob.upload_from_filename(source_path, **upload_kwargs)
        
        # Set metadata if provided
        if metadata:
            blob.metadata = metadata
            blob.patch()
        
        logger.info(f"Successfully uploaded to gs://{bucket_name}/{blob_name}")
        
        return {
            'status': 'success',
            'uri': f'gs://{bucket_name}/{blob_name}',
            'bucket': bucket_name,
            'blob': blob_name,
            'size': file_size,
            'content_type': blob.content_type,
            'message': f'Uploaded {file_size} bytes to GCS'
        }
        
    except Exception as e:
        logger.error(f"GCS upload failed: {e}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
            'message': f'Failed to upload to GCS: {e}'
        }


def _fetch_credential(credential_name: str) -> Optional[Dict[str, Any]]:
    """
    Fetch credential data from the NoETL server.
    
    Args:
        credential_name: Name of the credential to fetch
        
    Returns:
        Credential data dictionary or None if not found
    """
    import httpx
    
    try:
        base_url = os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082').rstrip('/')
        if not base_url.endswith('/api'):
            base_url = base_url + '/api'
            
        url = f"{base_url}/credentials/{credential_name}?include_data=true"
        
        logger.debug(f"Fetching credential from: {url}")
        
        with httpx.Client(timeout=5.0) as client:
            response = client.get(url)
            
            if response.status_code == 200:
                body = response.json() or {}
                raw = body.get('data') or {}
                
                # Handle nested data structure
                if isinstance(raw, dict) and isinstance(raw.get('data'), dict):
                    payload = raw.get('data')
                else:
                    payload = raw
                    
                return payload if isinstance(payload, dict) else {}
            else:
                logger.warning(f"Failed to fetch credential '{credential_name}': HTTP {response.status_code}")
                return None
                
    except Exception as e:
        logger.error(f"Failed to fetch credential '{credential_name}': {e}")
        return None
