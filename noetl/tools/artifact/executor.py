"""
Artifact task executor for loading/storing results from external storage.

This module provides functionality to:
- GET: Load externalized results from artifact storage (S3, GCS, filesystem)
- PUT: Store results to artifact storage (for explicit storage operations)

Usage in playbooks:
```yaml
- step: load_previous_result
  tool:
    kind: artifact
    action: get
    result_ref: "{{ previous_step.output_ref }}"
    # OR specify directly
    uri: "artifact://bucket-name/results/exec_123/step_abc.json.gz"
    
- step: store_large_result
  tool:
    kind: artifact
    action: put
    data: "{{ large_data }}"
    uri: "artifact://bucket-name/manual/data.json"
```
"""

import json
import gzip
import os
from typing import Dict, Any, Optional, Callable
from pathlib import Path
from urllib.parse import urlparse

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def execute_artifact_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Any,
    task_with: Dict[str, Any],
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute an artifact storage task (get or put).
    
    Args:
        task_config: Task configuration containing:
            - action: 'get' or 'put'
            - uri: Artifact URI (artifact://bucket/path or s3://... or gs://...)
            - result_ref: Optional result reference to look up
            - data: Data to store (for put action)
            - credential: Optional credential name for cloud storage
        context: Execution context
        jinja_env: Jinja2 environment for templating
        task_with: Additional task parameters
        log_event_callback: Optional callback for logging events
        
    Returns:
        Dict with action result
    """
    action = task_config.get('action') or task_with.get('action', 'get')
    
    if action == 'get':
        return execute_artifact_get(task_config, context, jinja_env, task_with, log_event_callback)
    elif action == 'put':
        return execute_artifact_put(task_config, context, jinja_env, task_with, log_event_callback)
    else:
        raise ValueError(f"Unknown artifact action: {action}. Supported: get, put")


def execute_artifact_get(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Any,
    task_with: Dict[str, Any],
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Load externalized result from artifact storage.
    
    Resolves result_ref or uri to actual storage location and loads data.
    
    Args:
        task_config: Task configuration with uri or result_ref
        context: Execution context
        jinja_env: Jinja2 environment
        task_with: Additional parameters
        log_event_callback: Event logging callback
        
    Returns:
        Dict with loaded result data
    """
    task_id = task_config.get('task_id', 'artifact_get')
    
    # Get URI - either directly or via result_ref lookup
    uri = task_config.get('uri') or task_with.get('uri')
    result_ref = task_config.get('result_ref') or task_with.get('result_ref')
    credential_name = task_config.get('credential') or task_with.get('credential')
    
    # If result_ref provided, look up in result_index
    if result_ref and not uri:
        uri = _lookup_result_ref(result_ref, context)
        if not uri:
            raise ValueError(f"Result reference not found: {result_ref}")
    
    if not uri:
        raise ValueError("artifact.get requires 'uri' or 'result_ref' parameter")
    
    logger.info(f"ARTIFACT GET: Loading from {uri}")
    
    # Parse URI to determine storage backend
    parsed = urlparse(uri)
    scheme = parsed.scheme
    
    if scheme in ('artifact', 'file', ''):
        # Local filesystem
        return _load_from_filesystem(uri, task_config)
    elif scheme == 's3':
        # AWS S3
        return _load_from_s3(uri, credential_name, context, task_config)
    elif scheme == 'gs':
        # Google Cloud Storage
        return _load_from_gcs(uri, credential_name, context, task_config)
    elif scheme == 'eventlog':
        # Event log (stored in database)
        return _load_from_eventlog(uri, context)
    else:
        raise ValueError(f"Unsupported artifact scheme: {scheme}")


def execute_artifact_put(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Any,
    task_with: Dict[str, Any],
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Store result to artifact storage.
    
    Args:
        task_config: Task configuration with uri and data
        context: Execution context
        jinja_env: Jinja2 environment
        task_with: Additional parameters
        log_event_callback: Event logging callback
        
    Returns:
        Dict with storage result including uri, size, sha256
    """
    task_id = task_config.get('task_id', 'artifact_put')
    
    uri = task_config.get('uri') or task_with.get('uri')
    data = task_config.get('data') or task_with.get('data')
    credential_name = task_config.get('credential') or task_with.get('credential')
    compress = task_config.get('compress', True)
    
    if not uri:
        raise ValueError("artifact.put requires 'uri' parameter")
    
    if data is None:
        raise ValueError("artifact.put requires 'data' parameter")
    
    logger.info(f"ARTIFACT PUT: Storing to {uri}")
    
    # Parse URI to determine storage backend
    parsed = urlparse(uri)
    scheme = parsed.scheme
    
    if scheme in ('artifact', 'file', ''):
        return _store_to_filesystem(uri, data, compress, task_config)
    elif scheme == 's3':
        return _store_to_s3(uri, data, compress, credential_name, context, task_config)
    elif scheme == 'gs':
        return _store_to_gcs(uri, data, compress, credential_name, context, task_config)
    else:
        raise ValueError(f"Unsupported artifact scheme for put: {scheme}")


def _lookup_result_ref(result_ref: str, context: Dict[str, Any]) -> Optional[str]:
    """Look up result_ref in result_index table to get logical_uri."""
    import httpx
    
    execution_id = context.get('execution_id')
    server_url = context.get('server_url', os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082'))
    
    # Query result_index via server API
    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(
                f"{server_url}/api/results/lookup",
                params={"result_ref": result_ref, "execution_id": execution_id}
            )
            if response.status_code == 200:
                data = response.json()
                return data.get('logical_uri')
            else:
                logger.warning(f"Result lookup failed: {response.status_code}")
                return None
    except Exception as e:
        logger.error(f"Error looking up result_ref: {e}")
        return None


def _load_from_filesystem(uri: str, task_config: Dict[str, Any]) -> Dict[str, Any]:
    """Load result from local filesystem."""
    # Parse path from URI
    if uri.startswith('artifact://'):
        # artifact://localfs/path/to/file
        path = uri.replace('artifact://localfs/', '/')
        path = path.replace('artifact://', '')
    elif uri.startswith('file://'):
        path = uri.replace('file://', '')
    else:
        path = uri
    
    # Expand user and resolve path
    path = os.path.expanduser(path)
    path = os.path.abspath(path)
    
    if not os.path.exists(path):
        raise FileNotFoundError(f"Artifact file not found: {path}")
    
    logger.debug(f"Loading artifact from filesystem: {path}")
    
    # Detect compression
    is_gzipped = path.endswith('.gz') or path.endswith('.gzip')
    
    # Read file
    if is_gzipped:
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            content = f.read()
    else:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    
    # Parse JSON
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # Return as raw string if not JSON
        data = content
    
    file_size = os.path.getsize(path)
    
    return {
        "status": "success",
        "data": data,
        "uri": uri,
        "size_bytes": file_size,
        "compressed": is_gzipped
    }


def _load_from_s3(uri: str, credential_name: Optional[str], context: Dict[str, Any], task_config: Dict[str, Any]) -> Dict[str, Any]:
    """Load result from AWS S3."""
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        raise ImportError("boto3 required for S3 artifact storage. Install with: pip install boto3")
    
    # Parse S3 URI
    parsed = urlparse(uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip('/')
    
    if not bucket or not key:
        raise ValueError(f"Invalid S3 URI: {uri}")
    
    logger.debug(f"Loading artifact from S3: s3://{bucket}/{key}")
    
    # Get credentials
    s3_config = {}
    if credential_name:
        creds = _fetch_credential(credential_name, context)
        if creds:
            s3_config['aws_access_key_id'] = creds.get('aws_access_key_id')
            s3_config['aws_secret_access_key'] = creds.get('aws_secret_access_key')
            if creds.get('region'):
                s3_config['region_name'] = creds.get('region')
    
    # Create S3 client
    s3 = boto3.client('s3', **s3_config)
    
    # Download object
    response = s3.get_object(Bucket=bucket, Key=key)
    body = response['Body'].read()
    content_length = response.get('ContentLength', len(body))
    
    # Decompress if gzipped
    is_gzipped = key.endswith('.gz') or key.endswith('.gzip')
    if is_gzipped:
        body = gzip.decompress(body)
    
    # Parse JSON
    content = body.decode('utf-8')
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        data = content
    
    return {
        "status": "success",
        "data": data,
        "uri": uri,
        "size_bytes": content_length,
        "compressed": is_gzipped
    }


def _load_from_gcs(uri: str, credential_name: Optional[str], context: Dict[str, Any], task_config: Dict[str, Any]) -> Dict[str, Any]:
    """Load result from Google Cloud Storage."""
    try:
        from google.cloud import storage
        from google.oauth2 import service_account
    except ImportError:
        raise ImportError("google-cloud-storage required for GCS artifact storage")
    
    # Parse GCS URI
    if not uri.startswith('gs://'):
        raise ValueError(f"Invalid GCS URI: {uri}")
    
    parts = uri[5:].split('/', 1)
    bucket_name = parts[0]
    blob_name = parts[1] if len(parts) > 1 else ''
    
    if not bucket_name or not blob_name:
        raise ValueError(f"Invalid GCS URI: {uri}")
    
    logger.debug(f"Loading artifact from GCS: gs://{bucket_name}/{blob_name}")
    
    # Get credentials
    client = None
    if credential_name:
        creds = _fetch_credential(credential_name, context)
        if creds and creds.get('service_account_json'):
            sa_json = creds['service_account_json']
            if isinstance(sa_json, str):
                sa_json = json.loads(sa_json)
            credentials = service_account.Credentials.from_service_account_info(sa_json)
            client = storage.Client(credentials=credentials, project=sa_json.get('project_id'))
    
    if not client:
        # Try default credentials
        client = storage.Client()
    
    # Download blob
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    
    content = blob.download_as_bytes()
    content_length = blob.size or len(content)
    
    # Decompress if gzipped
    is_gzipped = blob_name.endswith('.gz') or blob_name.endswith('.gzip')
    if is_gzipped:
        content = gzip.decompress(content)
    
    # Parse JSON
    text = content.decode('utf-8')
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = text
    
    return {
        "status": "success",
        "data": data,
        "uri": uri,
        "size_bytes": content_length,
        "compressed": is_gzipped
    }


def _load_from_eventlog(uri: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Load result from event log (stored in database)."""
    import httpx
    
    # Parse eventlog URI: eventlog://execution_id/event_id
    if not uri.startswith('eventlog://'):
        raise ValueError(f"Invalid eventlog URI: {uri}")
    
    parts = uri[11:].split('/')
    if len(parts) < 2:
        raise ValueError(f"Invalid eventlog URI format: {uri}")
    
    exec_id = parts[0]
    event_id = parts[1]
    
    server_url = context.get('server_url', os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082'))
    
    logger.debug(f"Loading artifact from eventlog: execution={exec_id}, event={event_id}")
    
    # Query event via server API
    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(f"{server_url}/api/events/{event_id}")
            if response.status_code == 200:
                event_data = response.json()
                result = event_data.get('result') or event_data.get('output_inline')
                return {
                    "status": "success",
                    "data": result,
                    "uri": uri,
                    "source": "eventlog"
                }
            else:
                raise ValueError(f"Event not found: {event_id}")
    except Exception as e:
        logger.error(f"Error loading from eventlog: {e}")
        raise


def _store_to_filesystem(uri: str, data: Any, compress: bool, task_config: Dict[str, Any]) -> Dict[str, Any]:
    """Store result to local filesystem."""
    import hashlib
    
    # Parse path from URI
    if uri.startswith('artifact://'):
        path = uri.replace('artifact://localfs/', '/')
        path = path.replace('artifact://', '')
    elif uri.startswith('file://'):
        path = uri.replace('file://', '')
    else:
        path = uri
    
    path = os.path.expanduser(path)
    path = os.path.abspath(path)
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    # Serialize data
    if isinstance(data, (dict, list)):
        content = json.dumps(data, indent=2)
    else:
        content = str(data)
    
    content_bytes = content.encode('utf-8')
    
    # Compute hash before compression
    sha256 = hashlib.sha256(content_bytes).hexdigest()
    
    # Add .gz extension if compressing
    if compress and not path.endswith('.gz'):
        path = path + '.gz'
    
    # Write file
    if compress:
        with gzip.open(path, 'wt', encoding='utf-8') as f:
            f.write(content)
    else:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
    
    file_size = os.path.getsize(path)
    
    logger.info(f"Stored artifact to filesystem: {path} ({file_size} bytes)")
    
    return {
        "status": "success",
        "uri": f"artifact://localfs{path}" if not uri.startswith('artifact://') else uri,
        "size_bytes": file_size,
        "sha256": sha256,
        "compressed": compress
    }


def _store_to_s3(uri: str, data: Any, compress: bool, credential_name: Optional[str], context: Dict[str, Any], task_config: Dict[str, Any]) -> Dict[str, Any]:
    """Store result to AWS S3."""
    import hashlib
    
    try:
        import boto3
    except ImportError:
        raise ImportError("boto3 required for S3 artifact storage")
    
    # Parse S3 URI
    parsed = urlparse(uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip('/')
    
    if not bucket or not key:
        raise ValueError(f"Invalid S3 URI: {uri}")
    
    # Serialize data
    if isinstance(data, (dict, list)):
        content = json.dumps(data)
    else:
        content = str(data)
    
    content_bytes = content.encode('utf-8')
    sha256 = hashlib.sha256(content_bytes).hexdigest()
    
    # Compress if requested
    if compress:
        content_bytes = gzip.compress(content_bytes)
        if not key.endswith('.gz'):
            key = key + '.gz'
    
    # Get credentials
    s3_config = {}
    if credential_name:
        creds = _fetch_credential(credential_name, context)
        if creds:
            s3_config['aws_access_key_id'] = creds.get('aws_access_key_id')
            s3_config['aws_secret_access_key'] = creds.get('aws_secret_access_key')
            if creds.get('region'):
                s3_config['region_name'] = creds.get('region')
    
    # Upload
    s3 = boto3.client('s3', **s3_config)
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=content_bytes,
        ContentType='application/json'
    )
    
    logger.info(f"Stored artifact to S3: s3://{bucket}/{key}")
    
    return {
        "status": "success",
        "uri": f"s3://{bucket}/{key}",
        "size_bytes": len(content_bytes),
        "sha256": sha256,
        "compressed": compress
    }


def _store_to_gcs(uri: str, data: Any, compress: bool, credential_name: Optional[str], context: Dict[str, Any], task_config: Dict[str, Any]) -> Dict[str, Any]:
    """Store result to Google Cloud Storage."""
    import hashlib
    
    try:
        from google.cloud import storage
        from google.oauth2 import service_account
    except ImportError:
        raise ImportError("google-cloud-storage required for GCS artifact storage")
    
    # Parse GCS URI
    if not uri.startswith('gs://'):
        raise ValueError(f"Invalid GCS URI: {uri}")
    
    parts = uri[5:].split('/', 1)
    bucket_name = parts[0]
    blob_name = parts[1] if len(parts) > 1 else ''
    
    # Serialize data
    if isinstance(data, (dict, list)):
        content = json.dumps(data)
    else:
        content = str(data)
    
    content_bytes = content.encode('utf-8')
    sha256 = hashlib.sha256(content_bytes).hexdigest()
    
    # Compress if requested
    if compress:
        content_bytes = gzip.compress(content_bytes)
        if not blob_name.endswith('.gz'):
            blob_name = blob_name + '.gz'
    
    # Get credentials
    client = None
    if credential_name:
        creds = _fetch_credential(credential_name, context)
        if creds and creds.get('service_account_json'):
            sa_json = creds['service_account_json']
            if isinstance(sa_json, str):
                sa_json = json.loads(sa_json)
            credentials = service_account.Credentials.from_service_account_info(sa_json)
            client = storage.Client(credentials=credentials, project=sa_json.get('project_id'))
    
    if not client:
        client = storage.Client()
    
    # Upload
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(content_bytes, content_type='application/json')
    
    logger.info(f"Stored artifact to GCS: gs://{bucket_name}/{blob_name}")
    
    return {
        "status": "success",
        "uri": f"gs://{bucket_name}/{blob_name}",
        "size_bytes": len(content_bytes),
        "sha256": sha256,
        "compressed": compress
    }


def _fetch_credential(credential_name: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Fetch credential from NoETL server."""
    import httpx
    
    server_url = context.get('server_url', os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082'))
    catalog_id = context.get('catalog_id')
    execution_id = context.get('execution_id')
    
    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(
                f"{server_url}/api/credentials/resolve/{credential_name}",
                params={"catalog_id": catalog_id, "execution_id": execution_id}
            )
            if response.status_code == 200:
                return response.json().get('credential', {})
            else:
                logger.warning(f"Credential fetch failed: {response.status_code}")
                return None
    except Exception as e:
        logger.error(f"Error fetching credential: {e}")
        return None
