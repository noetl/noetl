"""
GCS storage delegation for sink operations.

Handles uploading files to Google Cloud Storage buckets.
"""

from typing import Any, Callable, Dict, Optional
from jinja2 import Environment

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def handle_gcs_storage(
    tool_config: Dict[str, Any],
    rendered_data: Dict[str, Any],
    rendered_params: Dict[str, Any],
    auth_config: Optional[Dict[str, Any]],
    credential_ref: Optional[str],
    spec: Dict[str, Any],
    task_with: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    log_event_callback: Optional[Callable] = None,
) -> Dict[str, Any]:
    """
    Handle GCS storage sink operation by delegating to GCS tool.

    Args:
        tool_config: Sink tool configuration (kind, source, destination, credential, etc.)
        rendered_data: Rendered data context (may contain file path)
        rendered_params: Rendered parameters
        auth_config: Optional authentication configuration
        credential_ref: Credential reference key
        spec: Specification dictionary
        task_with: Task-level parameters
        context: Execution context
        jinja_env: Jinja2 environment for templating
        log_event_callback: Optional event logging callback

    Returns:
        Result dictionary from GCS upload operation
    """
    logger.info(f"GCS.STORAGE: Starting GCS sink handler with config: {tool_config}")
    
    try:
        # Import GCS executor
        from noetl.tools.gcs import execute_gcs_task
        
        # Extract source file path
        source = tool_config.get('source')
        if not source:
            # Try to extract from rendered_data if it's a file path string
            if isinstance(rendered_data, str):
                source = rendered_data
            elif isinstance(rendered_data, dict) and 'local_path' in rendered_data:
                source = rendered_data['local_path']
            else:
                raise ValueError("No source file path provided in sink configuration")
        
        logger.info(f"GCS.STORAGE: Source file: {source}")
        
        # Extract destination GCS URI
        destination = tool_config.get('destination')
        if not destination:
            raise ValueError("No destination GCS URI provided in sink configuration")
        
        logger.info(f"GCS.STORAGE: Destination URI: {destination}")
        
        # Extract credential reference
        credential = tool_config.get('credential') or credential_ref
        if not credential:
            raise ValueError("No credential provided for GCS upload")
        
        logger.info(f"GCS.STORAGE: Using credential: {credential}")
        
        # Build task config for GCS executor
        gcs_task_config = {
            'kind': 'gcs',
            'source': source,
            'destination': destination,
            'credential': credential,
        }
        
        # Add optional parameters
        if 'content_type' in tool_config:
            gcs_task_config['content_type'] = tool_config['content_type']
        
        if 'metadata' in tool_config:
            gcs_task_config['metadata'] = tool_config['metadata']
        
        logger.info(f"GCS.STORAGE: Task config: {gcs_task_config}")
        
        # Merge with task_with for additional context (handle None case)
        merged_task_with = {**(task_with or {}), **gcs_task_config}
        
        # Execute GCS upload via tool executor
        logger.info("GCS.STORAGE: Calling execute_gcs_task")
        result = execute_gcs_task(
            task_config=gcs_task_config,
            context=context,
            jinja_env=jinja_env,
            task_with=merged_task_with,
            log_event_callback=log_event_callback
        )
        
        logger.info(f"GCS.STORAGE: Result: {result}")
        
        # Normalize result format for sink operations
        if isinstance(result, dict):
            if result.get('status') == 'error':
                logger.error(f"GCS.STORAGE: Upload failed: {result.get('message')}")
                return {
                    'status': 'error',
                    'message': result.get('message', 'GCS upload failed'),
                    'error': result.get('error')
                }
            
            # Return success result with GCS metadata
            return {
                'status': 'success',
                'uri': result.get('uri'),
                'bucket': result.get('bucket'),
                'blob': result.get('blob'),
                'size': result.get('size'),
                'content_type': result.get('content_type'),
                'message': result.get('message', 'File uploaded to GCS successfully')
            }
        
        # Fallback for unexpected result format
        return {
            'status': 'success',
            'result': result,
            'message': 'GCS sink operation completed'
        }
        
    except Exception as e:
        logger.exception(f"GCS.STORAGE: Error in GCS sink handler: {e}")
        return {
            'status': 'error',
            'message': f"GCS sink failed: {str(e)}",
            'error': str(e)
        }
