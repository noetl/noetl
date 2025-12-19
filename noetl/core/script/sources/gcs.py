"""
Google Cloud Storage (GCS) script fetcher.
"""

import os
from typing import Optional, Dict, Any
from jinja2 import Environment
import httpx

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
        from google.oauth2 import service_account
        from google.auth import credentials as auth_credentials
        import google.auth.transport.requests
    except ImportError:
        pass  # Will use default credentials if service account not available
    
    try:
        # Resolve credentials
        credentials = None
        service_account_info = None
        oauth_user_info = None
        
        if credential:
            try:
                credential_data = _fetch_credential(credential)
                if credential_data:
                    # Handle different credential formats
                    # Service account JSON (google_service_account, google_oauth, gcp types)
                    if 'type' in credential_data and credential_data.get('type') == 'service_account':
                        service_account_info = credential_data
                        logger.debug(f"Using service account credentials from '{credential}'")
                    # OAuth authorized_user credentials
                    elif 'type' in credential_data and credential_data.get('type') == 'authorized_user':
                        oauth_user_info = credential_data
                        logger.debug(f"Using OAuth user credentials from '{credential}'")
                    # Nested data structure (credential wrapped in 'data' field)
                    elif 'data' in credential_data and isinstance(credential_data['data'], dict):
                        if credential_data['data'].get('type') == 'service_account':
                            service_account_info = credential_data['data']
                            logger.debug(f"Using service account credentials (nested) from '{credential}'")
                        elif credential_data['data'].get('type') == 'authorized_user':
                            oauth_user_info = credential_data['data']
                            logger.debug(f"Using OAuth user credentials (nested) from '{credential}'")
                    else:
                        logger.warning(f"GCS credential '{credential}' does not contain service account or OAuth user data")
                else:
                    logger.warning(f"GCS credential '{credential}' not found or empty")
            except Exception as e:
                logger.error(f"Failed to fetch GCS credential '{credential}': {e}")
                raise PermissionError(f"Failed to resolve GCS credential '{credential}': {e}")
        
        # Create GCS client
        logger.debug(f"Creating GCS client for bucket: {bucket}")
        if service_account_info:
            credentials = service_account.Credentials.from_service_account_info(service_account_info)
            client = storage.Client(credentials=credentials, project=service_account_info.get('project_id'))
        elif oauth_user_info:
            # Use OAuth user credentials (authorized_user)
            from google.oauth2.credentials import Credentials as OAuthCredentials
            credentials = OAuthCredentials(
                token=None,  # Will be refreshed automatically
                refresh_token=oauth_user_info.get('refresh_token'),
                token_uri='https://oauth2.googleapis.com/token',
                client_id=oauth_user_info.get('client_id'),
                client_secret=oauth_user_info.get('client_secret')
            )
            # Refresh the token before use
            request = google.auth.transport.requests.Request()
            credentials.refresh(request)
            # Use anonymous project parameter to avoid ADC lookup
            client = storage.Client(credentials=credentials, project='_')
        else:
            # Use application default credentials
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


def _fetch_credential(credential_name: str) -> Optional[Dict[str, Any]]:
    """
    Fetch credential data from the NoETL server.
    
    Args:
        credential_name: Name of the credential to fetch
        
    Returns:
        Credential data dictionary or None if not found
        
    Raises:
        Exception: If credential fetch fails
    """
    try:
        base_url = os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082').rstrip('/')
        if not base_url.endswith('/api'):
            base_url = base_url + '/api'
            
        url = f"{base_url}/credentials/{credential_name}?include_data=true"
        
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
        raise
