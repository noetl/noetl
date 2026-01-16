"""
Server-side keychain processor.

Processes the keychain section of a playbook at execution start,
creating keychain entries by:
1. Resolving secret_manager entries
2. Making OAuth2 token requests
3. Storing static credentials
4. Storing entries in noetl.keychain table
"""

import httpx
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from noetl.core.logger import setup_logger
from jinja2 import Template, Environment, StrictUndefined

logger = setup_logger(__name__, include_location=True)


async def process_keychain_section(
    keychain_section: List[Dict[str, Any]],
    catalog_id: int,
    execution_id: int,
    workload_vars: Dict[str, Any],
    api_base_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Process playbook keychain section at execution start.
    
    Creates keychain entries by executing the keychain definitions:
    - secret_manager: Fetch secrets from GCP/AWS/Azure
    - oauth2: Make OAuth2 token request
    - bearer: Store static bearer token
    - static: Store static credentials
    
    Args:
        keychain_section: List of keychain entry definitions from playbook
        catalog_id: Catalog ID of the playbook
        execution_id: Execution ID
        workload_vars: Workload variables for template rendering
        api_base_url: Base URL of NoETL API
        
    Returns:
        Dict mapping keychain names to their data (for immediate use if needed)
    """
    if not keychain_section:
        logger.debug("KEYCHAIN_PROCESSOR: No keychain section to process")
        return {}

    # Resolve API base URL (local dev-friendly)
    if not api_base_url:
        try:
            from noetl.core.config import settings
            api_base_url = settings.server_api_url or f"http://{settings.host}:{settings.port}"
        except Exception:
            api_base_url = "http://localhost:8082"

    api_base_url = _normalize_api_base_url(api_base_url)
    
    logger.debug(f"KEYCHAIN_PROCESSOR: Processing {len(keychain_section)} keychain entries for execution {execution_id} (api_base_url={api_base_url})")
    
    keychain_data = {}
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        for entry in keychain_section:
            entry_name = entry.get('name')
            # Accept either 'kind' or 'type' for entry classification
            entry_kind = entry.get('kind') or entry.get('type')
            
            if not entry_name or not entry_kind:
                logger.warning(f"KEYCHAIN_PROCESSOR: Skipping invalid entry: {entry}")
                continue
            
            logger.debug(f"KEYCHAIN_PROCESSOR: Processing entry '{entry_name}' (kind: {entry_kind})")
            
            if entry_kind == 'secret_manager':
                data = await _process_secret_manager(entry, workload_vars, keychain_data, client, api_base_url)
            elif entry_kind == 'oauth2':
                data = await _process_oauth2(entry, workload_vars, keychain_data, client)
            elif entry_kind == 'google_id_token':
                data = await _process_google_id_token(entry, workload_vars, keychain_data, client, api_base_url)
            elif entry_kind == 'bearer':
                data = await _process_bearer(entry, workload_vars, keychain_data)
            elif entry_kind == 'static':
                data = await _process_static(entry, workload_vars, keychain_data)
            elif entry_kind in ['credential', 'credential_ref', 'google_oauth', 'google_service_account', 'google']:
                data = await _process_credential_ref(entry, workload_vars, keychain_data, client, api_base_url)
            else:
                logger.warning(f"KEYCHAIN_PROCESSOR: Unknown kind '{entry_kind}' for entry '{entry_name}'")
                continue
            
            if data:
                # Store in keychain table
                success = await _store_keychain_entry(
                    client=client,
                    api_base_url=api_base_url,
                    catalog_id=catalog_id,
                    execution_id=execution_id,
                    keychain_name=entry_name,
                    token_data=data,
                    entry_def=entry
                )
                
                if success:
                    keychain_data[entry_name] = data
                    logger.debug(f"KEYCHAIN_PROCESSOR: Successfully stored entry '{entry_name}'")
                else:
                    raise RuntimeError(f"KEYCHAIN_PROCESSOR: Failed to store entry '{entry_name}' in database")
    
    logger.debug(f"KEYCHAIN_PROCESSOR: Completed processing {len(keychain_data)}/{len(keychain_section)} entries")
    return keychain_data


async def _process_secret_manager(
    entry: Dict[str, Any],
    workload_vars: Dict[str, Any],
    keychain_data: Dict[str, Any],
    client: httpx.AsyncClient,
    api_base_url: str
) -> Optional[Dict[str, Any]]:
    """Process secret_manager keychain entry by fetching secrets from GCP Secret Manager."""
    import base64
    
    provider = entry.get('provider', 'gcp')
    auth_ref = entry.get('auth')
    map_config = entry.get('map', {})
    
    if not auth_ref or not map_config:
        logger.error("KEYCHAIN_PROCESSOR: secret_manager requires 'auth' and 'map' fields")
        return None
    
    # Render auth reference
    env = Environment(undefined=StrictUndefined)
    auth_template = env.from_string(str(auth_ref))
    auth_name = auth_template.render(workload=workload_vars, keychain=keychain_data)
    
    logger.debug(f"KEYCHAIN_PROCESSOR: Fetching secrets from {provider} using auth '{auth_name}'")
    
    # Fetch credential to get auth data (should contain OAuth token or service account info)
    cred_response = await client.get(
        f"{api_base_url}/api/credentials/{auth_name}",
        params={"include_data": "true"}
    )
    if cred_response.status_code != 200:
        raise RuntimeError(
            f"KEYCHAIN_PROCESSOR: Failed to fetch credential '{auth_name}': {cred_response.status_code} - {cred_response.text}"
        )
    
    cred = cred_response.json()
    cred_type = cred.get('type', '')
    
    # Get access token based on credential type
    access_token = None
    if cred_type == 'oauth2':
        # OAuth credential should have access_token
        access_token = cred.get('data', {}).get('access_token')
    elif cred_type == 'google_oauth':
        # Use noetl.core.secret.obtain_gcp_token to get fresh token
        from noetl.core.secret import obtain_gcp_token
        cred_data = cred.get('data', {})
        token_result = obtain_gcp_token(
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
            credentials_info=cred_data
        )
        access_token = token_result.get('access_token')
    
    if not access_token:
        raise RuntimeError(f"KEYCHAIN_PROCESSOR: No access token available in credential '{auth_name}'")
    
    # Fetch secrets from GCP Secret Manager
    result_data = {}
    for key, secret_path_template in map_config.items():
        env = Environment(undefined=StrictUndefined)
        path_template = env.from_string(str(secret_path_template))
        secret_path = path_template.render(workload=workload_vars, keychain=keychain_data)
        
        logger.debug(f"KEYCHAIN_PROCESSOR: Fetching secret '{key}' from path: {secret_path}")
        
        # Call GCP Secret Manager API
        url = f"https://secretmanager.googleapis.com/v1/{secret_path}:access"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        response = await client.get(url, headers=headers, timeout=10.0)
        response.raise_for_status()
        data = response.json()
        
        # Decode base64 payload
        payload_data = data.get('payload', {}).get('data', '')
        if not payload_data:
            raise ValueError(f"KEYCHAIN_PROCESSOR: Empty payload for secret '{key}'")
        
        secret_value = base64.b64decode(payload_data).decode('UTF-8')
        
        # Try to parse as JSON
        try:
            import json
            result_data[key] = json.loads(secret_value)
        except:
            result_data[key] = secret_value
            
        logger.debug(f"KEYCHAIN_PROCESSOR: Successfully fetched secret '{key}'")
    
    return result_data


async def _process_oauth2(
    entry: Dict[str, Any],
    workload_vars: Dict[str, Any],
    keychain_data: Dict[str, Any],
    client: httpx.AsyncClient
) -> Optional[Dict[str, Any]]:
    """Process oauth2 keychain entry - make token request."""
    endpoint = entry.get('endpoint')
    method = entry.get('method', 'POST')
    headers = entry.get('headers', {})
    data_config = entry.get('data', {})
    
    if not endpoint:
        logger.error("KEYCHAIN_PROCESSOR: oauth2 requires 'endpoint' field")
        return None
    
    # Render templates in endpoint, headers, and data
    env = Environment(undefined=StrictUndefined)
    
    # Render endpoint
    endpoint_template = env.from_string(str(endpoint))
    rendered_endpoint = endpoint_template.render(workload=workload_vars, keychain=keychain_data)
    
    # Render headers
    rendered_headers = {}
    for k, v in headers.items():
        template = env.from_string(str(v))
        rendered_headers[k] = template.render(workload=workload_vars, keychain=keychain_data)
    
    # Render data
    rendered_data = {}
    for k, v in data_config.items():
        template = env.from_string(str(v))
        rendered_data[k] = template.render(workload=workload_vars, keychain=keychain_data)
    
    logger.debug(f"KEYCHAIN_PROCESSOR: Making OAuth2 request to {rendered_endpoint}")
    
    # Make OAuth2 request
    response = await client.request(
        method=method,
        url=rendered_endpoint,
        headers=rendered_headers,
        data=rendered_data
    )
    response.raise_for_status()
    
    token_data = response.json()
    logger.debug(f"KEYCHAIN_PROCESSOR: OAuth2 request successful, got token")
    return token_data


async def _process_google_id_token(
    entry: Dict[str, Any],
    workload_vars: Dict[str, Any],
    keychain_data: Dict[str, Any],
    client: httpx.AsyncClient,
    api_base_url: str
) -> Optional[Dict[str, Any]]:
    """
    Process google_id_token keychain entry - generate Google ID token from service account.
    
    Fetches service account credentials from either:
    1. Google Secret Manager (using 'service_account_secret')
    2. NoETL credential table (using 'service_account_credential')
    
    Then generates an ID token with the specified audience (target service URL).
    
    Expected entry format (Secret Manager):
    {
        "name": "pcc_id_token",
        "kind": "google_id_token",
        "scope": "global",
        "auto_renew": true,
        "auth": "{{ workload.gcp_auth }}",  # Credential for Secret Manager access
        "service_account_secret": "projects/123/secrets/my-sa/versions/latest",
        "target_audience": "https://my-service-abc123.run.app"
    }
    
    Expected entry format (Credential table):
    {
        "name": "pcc_id_token",
        "kind": "google_id_token",
        "scope": "global",
        "auto_renew": true,
        "service_account_credential": "my_service_account_credential",
        "target_audience": "https://my-service-abc123.run.app"
    }
    
    Args:
        entry: Keychain entry definition
        workload_vars: Workload variables for template rendering
        keychain_data: Previously resolved keychain data
        client: HTTP client for API calls
        api_base_url: NoETL API base URL
        
    Returns:
        Dict with 'id_token' and 'token_type' fields
    """
    import base64
    import json
    
    sa_secret_path_template = entry.get('service_account_secret')
    sa_credential_template = entry.get('service_account_credential')
    target_audience_template = entry.get('target_audience')
    
    # Validate required fields based on mode
    if not target_audience_template:
        logger.error("KEYCHAIN_PROCESSOR: google_id_token requires 'target_audience' field")
        return None
    
    if not sa_secret_path_template and not sa_credential_template:
        logger.error("KEYCHAIN_PROCESSOR: google_id_token requires either 'service_account_secret' or 'service_account_credential' field")
        return None
    
    if sa_secret_path_template and sa_credential_template:
        logger.error("KEYCHAIN_PROCESSOR: google_id_token cannot have both 'service_account_secret' and 'service_account_credential' - use one or the other")
        return None
    
    # Render templates
    env = Environment(undefined=StrictUndefined)
    
    # Render target audience
    audience_template = env.from_string(str(target_audience_template))
    target_audience = audience_template.render(workload=workload_vars, keychain=keychain_data)
    
    logger.debug(f"KEYCHAIN_PROCESSOR: Generating Google ID token for audience: {target_audience}")
    
    # Determine service account source and fetch SA info
    sa_info = None
    
    if sa_credential_template:
        # Mode 1: Fetch service account from credential table
        logger.debug(f"KEYCHAIN_PROCESSOR: Fetching service account from credential table")
        
        # Render credential name
        sa_cred_template = env.from_string(str(sa_credential_template))
        sa_cred_name = sa_cred_template.render(workload=workload_vars, keychain=keychain_data)
        
        # Fetch credential
        cred_response = await client.get(
            f"{api_base_url}/api/credentials/{sa_cred_name}",
            params={"include_data": "true"}
        )
        if cred_response.status_code != 200:
            raise RuntimeError(
                f"KEYCHAIN_PROCESSOR: Failed to fetch service account credential '{sa_cred_name}': {cred_response.status_code} - {cred_response.text}"
            )
        
        cred = cred_response.json()
        cred_type = cred.get('type', '')
        cred_data = cred.get('data', {})
        
        # Extract service account info based on credential structure
        if cred_type in ['google_oauth', 'google_service_account', 'gcp']:
            # Check if credential has nested service_account_info
            if 'service_account_info' in cred_data:
                sa_info = cred_data['service_account_info']
            # Or if the data itself is the service account
            elif cred_data.get('type') == 'service_account':
                sa_info = cred_data
            else:
                raise ValueError(
                    f"KEYCHAIN_PROCESSOR: Credential '{sa_cred_name}' does not contain valid service account info. "
                    f"Expected 'service_account_info' field or 'type=service_account' structure."
                )
        else:
            raise RuntimeError(
                f"KEYCHAIN_PROCESSOR: Credential '{sa_cred_name}' must be of type 'google_oauth', 'google_service_account', or 'gcp' (found: {cred_type})"
            )
        
        logger.debug(f"KEYCHAIN_PROCESSOR: Service account loaded from credential: {sa_info.get('client_email')}")
    
    elif sa_secret_path_template:
        # Mode 2: Fetch service account from Secret Manager
        logger.debug(f"KEYCHAIN_PROCESSOR: Fetching service account from Secret Manager")
        
        # Validate auth field is present for Secret Manager access
        auth_ref = entry.get('auth')
        if not auth_ref:
            logger.error("KEYCHAIN_PROCESSOR: google_id_token requires 'auth' field when using 'service_account_secret'")
            return None
        
        # Render auth reference
        auth_template = env.from_string(str(auth_ref))
        auth_name = auth_template.render(workload=workload_vars, keychain=keychain_data)
        
        # Render service account secret path
        sa_path_template = env.from_string(str(sa_secret_path_template))
        sa_secret_path = sa_path_template.render(workload=workload_vars, keychain=keychain_data)
        
        # Fetch credential to get auth data
        cred_response = await client.get(
            f"{api_base_url}/api/credentials/{auth_name}",
            params={"include_data": "true"}
        )
        if cred_response.status_code != 200:
            raise RuntimeError(
                f"KEYCHAIN_PROCESSOR: Failed to fetch credential '{auth_name}': {cred_response.status_code} - {cred_response.text}"
            )
        
        cred = cred_response.json()
        cred_type = cred.get('type', '')
        
        # Get access token for Secret Manager API
        access_token = None
        if cred_type in ['google_oauth', 'google_service_account', 'gcp']:
            from noetl.core.auth.google_provider import GoogleTokenProvider
            provider = GoogleTokenProvider(cred.get('data', {}))
            access_token = provider.fetch_token()
        else:
            raise RuntimeError(
                f"KEYCHAIN_PROCESSOR: Auth credential '{auth_name}' must be google_oauth or google_service_account type"
            )
        
        # Fetch service account JSON from Secret Manager
        logger.debug(f"KEYCHAIN_PROCESSOR: Fetching service account from: {sa_secret_path}")
        sm_url = f"https://secretmanager.googleapis.com/v1/{sa_secret_path}:access"
        sm_headers = {"Authorization": f"Bearer {access_token}"}
        
        sm_response = await client.get(sm_url, headers=sm_headers, timeout=10.0)
        sm_response.raise_for_status()
        sm_data = sm_response.json()
        
        # Decode base64 payload
        payload_data = sm_data.get('payload', {}).get('data', '')
        if not payload_data:
            raise ValueError(f"KEYCHAIN_PROCESSOR: Empty payload for service account secret")
        
        sa_json_str = base64.b64decode(payload_data).decode('UTF-8')
        sa_info = json.loads(sa_json_str)
        
        logger.debug(f"KEYCHAIN_PROCESSOR: Service account loaded from Secret Manager: {sa_info.get('client_email')}")
    
    # Validate service account structure
    if not sa_info or sa_info.get('type') != 'service_account':
        raise ValueError(
            f"KEYCHAIN_PROCESSOR: Invalid service account structure. Must have 'type=service_account'. "
            f"Got: {sa_info.get('type') if sa_info else 'None'}"
        )
    
    # Generate ID token using Google OAuth library
    try:
        import google.auth.transport.requests
        from google.oauth2.service_account import IDTokenCredentials
        
        # Create ID token credentials with target audience
        id_creds = IDTokenCredentials.from_service_account_info(
            sa_info,
            target_audience=target_audience
        )
        
        # Fetch the ID token
        auth_req = google.auth.transport.requests.Request()
        id_creds.refresh(auth_req)
        
        if not id_creds.token:
            raise Exception("Failed to obtain ID token from service account")
        
        logger.debug(f"KEYCHAIN_PROCESSOR: Successfully generated Google ID token for audience: {target_audience}")
        
        return {
            'id_token': id_creds.token,
            'access_token': id_creds.token,  # Alias for compatibility with Bearer auth patterns
            'token_type': 'Bearer',
            'audience': target_audience
        }
        
    except Exception as e:
        logger.error(f"KEYCHAIN_PROCESSOR: Failed to generate ID token: {e}", exc_info=True)
        raise RuntimeError(f"KEYCHAIN_PROCESSOR: Failed to generate ID token: {e}")


async def _process_bearer(
    entry: Dict[str, Any],
    workload_vars: Dict[str, Any],
    keychain_data: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Process bearer keychain entry - static bearer token."""
    token = entry.get('token')
    
    if not token:
        logger.error("KEYCHAIN_PROCESSOR: bearer requires 'token' field")
        return None
    
    # Render token template
    env = Environment(undefined=StrictUndefined)
    token_template = env.from_string(str(token))
    rendered_token = token_template.render(workload=workload_vars, keychain=keychain_data)
    
    return {"access_token": rendered_token, "token_type": "Bearer"}


async def _process_static(
    entry: Dict[str, Any],
    workload_vars: Dict[str, Any],
    keychain_data: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Process static keychain entry - static credentials."""
    map_config = entry.get('map', {})
    
    if not map_config:
        logger.error("KEYCHAIN_PROCESSOR: static requires 'map' field")
        return None
    
    # Render all map values
    env = Environment(undefined=StrictUndefined)
    result_data = {}
    
    for key, value_template in map_config.items():
        template = env.from_string(str(value_template))
        result_data[key] = template.render(workload=workload_vars, keychain=keychain_data)
    
    return result_data


async def _process_credential_ref(
    entry: Dict[str, Any],
    workload_vars: Dict[str, Any],
    keychain_data: Dict[str, Any],
    client: httpx.AsyncClient,
    api_base_url: str
) -> Optional[Dict[str, Any]]:
    """Fetch an existing credential and cache its data as a keychain entry."""
    ref = entry.get('ref') or entry.get('credential') or entry.get('name')
    if not ref:
        logger.error("KEYCHAIN_PROCESSOR: credential_ref requires 'ref' or 'credential' field")
        return None

    env = Environment(undefined=StrictUndefined)
    ref_rendered = env.from_string(str(ref)).render(workload=workload_vars, keychain=keychain_data)

    resp = await client.get(
        f"{api_base_url}/api/credentials/{ref_rendered}",
        params={"include_data": "true"}
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"KEYCHAIN_PROCESSOR: Failed to fetch credential '{ref_rendered}': {resp.status_code} - {resp.text}"
        )

    cred = resp.json()
    if not cred.get('data'):
        raise RuntimeError(f"KEYCHAIN_PROCESSOR: Credential '{ref_rendered}' has no data to cache")

    credential_type = cred.get('type', 'generic')
    credential_data = cred['data']

    # For Google OAuth credentials, generate token (ID token if target_audience specified, else access token)
    if credential_type in ['google_oauth', 'google_service_account', 'gcp']:
        # Check if target_audience is specified in credential data
        target_audience = credential_data.get('target_audience')
        token_type_desc = f"ID token for audience '{target_audience}'" if target_audience else "access token"
        logger.debug(f"KEYCHAIN_PROCESSOR: Generating {token_type_desc} for credential '{ref_rendered}' (type: {credential_type})")
        try:
            from noetl.core.auth.google_provider import GoogleTokenProvider
            provider = GoogleTokenProvider(credential_data)
            # Pass audience if specified (generates ID token), otherwise None (generates access token)
            token = provider.fetch_token(audience=target_audience)
            logger.debug(f"KEYCHAIN_PROCESSOR: Successfully generated {token_type_desc} for '{ref_rendered}'")
            return {
                'access_token': token,
                'token_type': 'Bearer'
            }
        except Exception as e:
            logger.error(f"KEYCHAIN_PROCESSOR: Failed to generate {token_type_desc} for '{ref_rendered}': {e}", exc_info=True)
            raise RuntimeError(f"KEYCHAIN_PROCESSOR: Failed to generate {token_type_desc} for '{ref_rendered}': {e}")
    
    # For other credential types, return data as-is
    return credential_data


async def _store_keychain_entry(
    client: httpx.AsyncClient,
    api_base_url: str,
    catalog_id: int,
    execution_id: int,
    keychain_name: str,
    token_data: Dict[str, Any],
    entry_def: Dict[str, Any]
) -> bool:
    """Store keychain entry via API."""
    scope_type = entry_def.get('scope', 'global')
    auto_renew = entry_def.get('auto_renew', False)
    ttl_seconds = entry_def.get('ttl_seconds')
    
    # Calculate expiration
    if ttl_seconds:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    elif 'expires_in' in token_data:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_data['expires_in'])
    else:
        # Default TTL based on scope
        default_ttl = 86400 if scope_type in ['global', 'catalog', 'shared'] else 3600
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=default_ttl)
    
    # Build renew_config for oauth2 and google_id_token entries
    renew_config = None
    entry_kind = entry_def.get('kind')
    if auto_renew and entry_kind == 'oauth2':
        renew_config = {
            'endpoint': entry_def.get('endpoint'),
            'method': entry_def.get('method', 'POST'),
            'headers': entry_def.get('headers', {}),
            'data': entry_def.get('data', {})
        }
    elif auto_renew and entry_kind == 'google_id_token':
        renew_config = {
            'target_audience': entry_def.get('target_audience')
        }
        # Include either service_account_secret or service_account_credential
        if entry_def.get('service_account_secret'):
            renew_config['auth'] = entry_def.get('auth')
            renew_config['service_account_secret'] = entry_def.get('service_account_secret')
        elif entry_def.get('service_account_credential'):
            renew_config['service_account_credential'] = entry_def.get('service_account_credential')
    
    # Determine credential_type
    credential_type = entry_kind or 'unknown'
    if credential_type == 'oauth2':
        credential_type = 'oauth2_client_credentials'
    elif credential_type == 'google_id_token':
        credential_type = 'google_id_token'
    
    # Build request payload
    payload = {
        'token_data': token_data,
        'credential_type': credential_type,
        'cache_type': 'token' if credential_type in ['oauth2_client_credentials', 'google_id_token', 'bearer'] else 'secret',
        'scope_type': scope_type,
        'execution_id': execution_id if scope_type == 'local' else None,
        'expires_at': expires_at.isoformat(),
        'auto_renew': auto_renew,
        'renew_config': renew_config
    }
    
    response = await client.post(
        f"{api_base_url}/api/keychain/{catalog_id}/{keychain_name}",
        json=payload
    )
    
    if response.status_code != 200:
        raise RuntimeError(f"KEYCHAIN_PROCESSOR: Failed to store '{keychain_name}': {response.status_code} - {response.text}")
    
    logger.debug(f"KEYCHAIN_PROCESSOR: Stored keychain entry '{keychain_name}'")
    return True


def _normalize_api_base_url(url: str) -> str:
    """Drop trailing slashes and duplicate /api segments to avoid double-prefixing."""
    if not url:
        return ""

    normalized = url.rstrip('/')
    if normalized.endswith('/api'):
        normalized = normalized[:-4]
    return normalized
