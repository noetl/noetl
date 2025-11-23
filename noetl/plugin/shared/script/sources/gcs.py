"""
Google Cloud Storage (GCS) script fetcher.
"""

from typing import Optional, Dict, Any
from jinja2 import Environment

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def fetch_from_gcs(
    path: str,
    bucket: str,
    credential: Optional[str],
    context: Dict[str, Any],
    jinja_env: Environment
) -> str:
    """
    Fetch script content from Google Cloud Storage.
    
    Args:
        path: Object path within bucket (e.g., 'scripts/transform.py')
        bucket: GCS bucket name
        credential: Credential reference for authentication
        context: Execution context
        jinja_env: Jinja2 environment
        
    Returns:
        Script content as string
        
    Raises:
        ImportError: google-cloud-storage not installed
        FileNotFoundError: Object not found in bucket
        PermissionError: Insufficient permissions
        ConnectionError: Network/API error
        
    Authentication:
        - Service account JSON key
        - Application default credentials (ADC)
        - HMAC credentials
    """
    try:
        from google.cloud import storage
        from google.auth import exceptions as auth_exceptions
    except ImportError:
        raise ImportError(
            "google-cloud-storage is required for GCS script sources. "
            "Install with: pip install google-cloud-storage"
        )
    
    try:
        # Resolve credentials
        credentials = None
        if credential:
            # TODO: Integrate with NoETL credential system
            # credentials = resolve_gcp_credential(credential, context, jinja_env)
            logger.warning(f"GCS credential resolution not yet implemented: {credential}")
            pass
        
        # Create GCS client
        logger.debug(f"Creating GCS client for bucket: {bucket}")
        client = storage.Client(credentials=credentials)
        
        # Get bucket and blob
        bucket_obj = client.bucket(bucket)
        blob = bucket_obj.blob(path)
        
        # Check if object exists
        if not blob.exists():
            raise FileNotFoundError(f"Script not found: gs://{bucket}/{path}")
        
        # Download content
        logger.info(f"Downloading script from gs://{bucket}/{path}")
        content = blob.download_as_text()
        
        logger.info(f"Successfully fetched {len(content)} bytes from GCS")
        return content
    
    except auth_exceptions.DefaultCredentialsError as e:
        logger.error(f"GCS authentication failed: {e}")
        raise PermissionError(f"GCS authentication failed: {e}")
    
    except FileNotFoundError:
        raise
    
    except Exception as e:
        logger.error(f"Error fetching script from GCS: {e}")
        raise ConnectionError(f"Failed to fetch from gs://{bucket}/{path}: {e}")
