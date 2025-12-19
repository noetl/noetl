"""
AWS S3 script fetcher.
"""

import os
from typing import Optional, Dict, Any
from jinja2 import Environment
import httpx

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def fetch_from_s3(
    path: str,
    bucket: str,
    region: Optional[str],
    credential: Optional[str],
    context: Dict[str, Any],
    jinja_env: Environment
) -> str:
    """
    Fetch script content from AWS S3.
    
    Args:
        path: Object key within bucket (e.g., 'scripts/transform.py')
        bucket: S3 bucket name
        region: AWS region (optional, will auto-detect if not provided)
        credential: Credential reference for authentication
        context: Execution context
        jinja_env: Jinja2 environment
        
    Returns:
        Script content as string
        
    Raises:
        ImportError: boto3 not installed
        FileNotFoundError: Object not found in bucket
        PermissionError: Insufficient IAM permissions
        ConnectionError: Network/API error
        
    Authentication:
        - AWS access key ID and secret access key
        - IAM role credentials (when running on EC2/ECS)
        - Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
    """
    try:
        import boto3
        from botocore.exceptions import ClientError, NoCredentialsError
    except ImportError:
        raise ImportError(
            "boto3 is required for S3 script sources. "
            "Install with: pip install boto3"
        )
    
    try:
        # Resolve credentials
        aws_access_key_id = None
        aws_secret_access_key = None
        
        if credential:
            try:
                credential_data = _fetch_credential(credential)
                if credential_data:
                    # Support multiple key naming conventions
                    aws_access_key_id = (
                        credential_data.get('access_key_id') or
                        credential_data.get('key_id') or
                        credential_data.get('aws_access_key_id')
                    )
                    aws_secret_access_key = (
                        credential_data.get('secret_access_key') or
                        credential_data.get('secret_key') or
                        credential_data.get('secret') or
                        credential_data.get('aws_secret_access_key')
                    )
                    
                    # Override region if specified in credential
                    if not region and 'region' in credential_data:
                        region = credential_data['region']
                    
                    if aws_access_key_id and aws_secret_access_key:
                        logger.debug(f"Using AWS credentials from '{credential}'")
                    else:
                        logger.warning(f"S3 credential '{credential}' missing access_key_id or secret_access_key")
                else:
                    logger.warning(f"S3 credential '{credential}' not found or empty")
            except Exception as e:
                logger.error(f"Failed to fetch S3 credential '{credential}': {e}")
                raise PermissionError(f"Failed to resolve S3 credential '{credential}': {e}")
        
        # Create S3 client
        logger.debug(f"Creating S3 client for bucket: {bucket}")
        s3_kwargs = {}
        if region:
            s3_kwargs['region_name'] = region
        if aws_access_key_id and aws_secret_access_key:
            s3_kwargs['aws_access_key_id'] = aws_access_key_id
            s3_kwargs['aws_secret_access_key'] = aws_secret_access_key
        
        client = boto3.client('s3', **s3_kwargs)
        
        # Fetch object
        logger.info(f"Downloading script from s3://{bucket}/{path}")
        response = client.get_object(Bucket=bucket, Key=path)
        
        # Read content
        content = response['Body'].read().decode('utf-8')
        
        logger.info(f"Successfully fetched {len(content)} bytes from S3")
        return content
    
    except NoCredentialsError as e:
        logger.error(f"S3 authentication failed: {e}")
        raise PermissionError(f"S3 authentication failed: {e}")
    
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == '404' or error_code == 'NoSuchKey':
            raise FileNotFoundError(f"Script not found: s3://{bucket}/{path}")
        elif error_code == '403' or error_code == 'AccessDenied':
            raise PermissionError(f"Access denied to s3://{bucket}/{path}")
        else:
            logger.error(f"S3 error: {e}")
            raise ConnectionError(f"Failed to fetch from s3://{bucket}/{path}: {e}")
    
    except Exception as e:
        logger.error(f"Error fetching script from S3: {e}")
        raise ConnectionError(f"Failed to fetch from s3://{bucket}/{path}: {e}")


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
