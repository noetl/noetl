"""Script loading utilities for external code execution."""
import logging

from noetl.core.logger import setup_logger
logger = setup_logger(__name__, include_location=True)


async def load_script_content(script_config: dict) -> str:
    """Load script content from external source (GCS, S3, file, HTTP)."""
    uri = script_config.get("uri", "")
    source = script_config.get("source", {})
    source_type = source.get("type", "")
    
    if not uri:
        raise ValueError("Script URI is required")
    
    # GCS: gs://bucket/path
    if uri.startswith("gs://") or source_type == "gcs":
        return await load_from_gcs(uri, source)
    
    # S3: s3://bucket/path
    elif uri.startswith("s3://") or source_type == "s3":
        return await load_from_s3(uri, source)
    
    # File: ./path or /abs/path
    elif source_type == "file" or uri.startswith("./") or uri.startswith("/"):
        return await load_from_file(uri)
    
    # HTTP
    elif source_type == "http" or uri.startswith("http://") or uri.startswith("https://"):
        return await load_from_http(uri, source)
    
    else:
        raise ValueError(f"Unsupported script source type: {source_type} or URI: {uri}")


async def load_from_gcs(uri: str, source: dict) -> str:
    """Load script from Google Cloud Storage."""
    
    try:
        from google.cloud import storage
        from google.oauth2 import service_account
        from google.oauth2.credentials import Credentials as UserCredentials
        
        # Parse gs://bucket/path
        if not uri.startswith("gs://"):
            raise ValueError(f"GCS URI must start with gs://: {uri}")
        
        path_parts = uri[5:].split("/", 1)
        bucket_name = path_parts[0]
        blob_path = path_parts[1] if len(path_parts) > 1 else ""
        
        # Handle authentication
        client = None
        auth_key = source.get("auth")
        logger.debug(f"[SCRIPT_LOADER] auth_key={auth_key} | source={source}")
        
        if auth_key:
            from noetl.worker.secrets import fetch_credential_by_key
            credential = fetch_credential_by_key(auth_key)
            
            if not credential or not credential.get("data"):
                raise ValueError(f"Failed to resolve GCS credential: {auth_key}")
            
            cred_data = credential.get("data", {})
            logger.debug(f"[SCRIPT_LOADER] credential_fetched={credential is not None} | cred_data_keys={list(cred_data.keys())}")
            
            # Support OAuth user credentials (refresh_token)
            if "refresh_token" in cred_data and "client_id" in cred_data:
                logger.debug(f"[SCRIPT_LOADER] Using OAuth credentials")
                credentials = UserCredentials(
                    token=None,  # Will be refreshed
                    refresh_token=cred_data["refresh_token"],
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=cred_data["client_id"],
                    client_secret=cred_data.get("client_secret")
                )
                # Extract project from bucket URI or use a dummy project
                # GCS doesn't require project for reading with valid credentials
                client = storage.Client(credentials=credentials, project="noetl-gcs")
                logger.debug(f"[SCRIPT_LOADER] Created storage client with OAuth")
            
            # Support service account JSON
            elif "service_account_json" in cred_data:
                logger.debug(f"[SCRIPT_LOADER] Using service account credentials")
                import json
                # Handle both string and dict formats
                sa_data = cred_data["service_account_json"]
                if isinstance(sa_data, str):
                    sa_info = json.loads(sa_data)
                else:
                    sa_info = sa_data
                credentials = service_account.Credentials.from_service_account_info(sa_info)
                client = storage.Client(credentials=credentials, project=sa_info.get("project_id"))
                logger.debug(f"[SCRIPT_LOADER] Created storage client with service account, project={sa_info.get('project_id')}")
            
            # Use project ID with default credentials
            elif "project_id" in cred_data:
                client = storage.Client(project=cred_data["project_id"])
        
        if not client:
            # Use default credentials (ADC)
            client = storage.Client()
        
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        
        content = blob.download_as_text()
        return content
        
    except Exception as e:
        raise ValueError(f"Failed to load script from GCS {uri}: {e}")


async def load_from_s3(uri: str, source: dict) -> str:
    """Load script from AWS S3."""
    try:
        import boto3
        
        # Parse s3://bucket/path
        if not uri.startswith("s3://"):
            raise ValueError(f"S3 URI must start with s3://: {uri}")
        
        path_parts = uri[5:].split("/", 1)
        bucket_name = path_parts[0]
        key = path_parts[1] if len(path_parts) > 1 else ""
        
        region = source.get("region")
        
        # Handle authentication
        auth_key = source.get("auth")
        s3_client_kwargs = {}
        
        if region:
            s3_client_kwargs["region_name"] = region
        
        if auth_key:
            from noetl.worker.secrets import fetch_credential_by_key
            credential = fetch_credential_by_key(auth_key)
            
            if not credential or not credential.get("data"):
                raise ValueError(f"Failed to resolve S3 credential: {auth_key}")
            
            cred_data = credential.get("data", {})
            
            # Support AWS access key/secret
            if "aws_access_key_id" in cred_data and "aws_secret_access_key" in cred_data:
                s3_client_kwargs["aws_access_key_id"] = cred_data["aws_access_key_id"]
                s3_client_kwargs["aws_secret_access_key"] = cred_data["aws_secret_access_key"]
                
                if "aws_session_token" in cred_data:
                    s3_client_kwargs["aws_session_token"] = cred_data["aws_session_token"]
        
        s3 = boto3.client("s3", **s3_client_kwargs)
        response = s3.get_object(Bucket=bucket_name, Key=key)
        content = response["Body"].read().decode("utf-8")
        return content
        
    except Exception as e:
        raise ValueError(f"Failed to load script from S3 {uri}: {e}")


async def load_from_file(uri: str) -> str:
    """Load script from local file."""
    try:
        import os
        
        # Resolve relative paths
        if uri.startswith("./"):
            uri = os.path.abspath(uri)
        
        with open(uri, "r") as f:
            content = f.read()
        return content
        
    except Exception as e:
        raise ValueError(f"Failed to load script from file {uri}: {e}")


async def load_from_http(uri: str, source: dict) -> str:
    """Load script from HTTP endpoint."""
    try:
        import httpx
        
        endpoint = source.get("endpoint", "")
        method = source.get("method", "GET").upper()
        headers = source.get("headers", {})
        timeout = source.get("timeout", 30)
        
        # Build full URL
        if uri.startswith("http://") or uri.startswith("https://"):
            url = uri
        elif endpoint:
            url = f"{endpoint.rstrip('/')}/{uri.lstrip('/')}"
        else:
            raise ValueError("HTTP source requires either full URI or endpoint + relative path")
        
        async with httpx.AsyncClient() as client:
            response = await client.request(method, url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.text
            
    except Exception as e:
        raise ValueError(f"Failed to load script from HTTP {uri}: {e}")
