"""
AWS S3 script fetcher.
"""

from typing import Optional, Dict, Any
from jinja2 import Environment

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
            # TODO: Integrate with NoETL credential system
            # creds = resolve_aws_credential(credential, context, jinja_env)
            # aws_access_key_id = creds.get('access_key_id')
            # aws_secret_access_key = creds.get('secret_access_key')
            logger.warning(f"S3 credential resolution not yet implemented: {credential}")
            pass
        
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
