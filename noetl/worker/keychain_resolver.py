"""
Keychain resolver for workers.

Resolves {{ keychain.* }} references by calling the keychain API
and populating the context with keychain entries.
"""

import re
import httpx
from typing import Dict, Any, Optional, Set
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


async def _renew_token(
    keychain_name: str,
    renew_config: Dict[str, Any],
    client: httpx.AsyncClient
) -> Optional[Dict[str, Any]]:
    """
    Renew an expired token using the renew_config.
    
    Args:
        keychain_name: Name of the keychain entry
        renew_config: Renewal configuration containing endpoint, method, headers, data, etc.
        client: HTTP client to use for the request
        
    Returns:
        Renewed token data dict or None if renewal fails
        
    Expected renew_config structure:
    {
        "endpoint": "https://api.example.com/oauth2/token",
        "method": "POST",
        "headers": {"Content-Type": "application/x-www-form-urlencoded"},
        "data": {"grant_type": "client_credentials", "client_id": "...", "client_secret": "..."},
        "json": {...},  # Optional: JSON payload
        "token_field": "access_token",  # Optional: field name in response (default: "access_token")
        "ttl_field": "expires_in"  # Optional: TTL field name (default: "expires_in")
    }
    """
    try:
        endpoint = renew_config.get('endpoint')
        method = renew_config.get('method', 'POST').upper()
        headers = renew_config.get('headers', {})
        data = renew_config.get('data')
        json_payload = renew_config.get('json')
        token_field = renew_config.get('token_field', 'access_token')
        
        if not endpoint:
            logger.error(f"KEYCHAIN: No endpoint in renew_config for '{keychain_name}'")
            return None
        
        logger.debug(f"KEYCHAIN: Renewing token via {method} {endpoint}")
        
        # Make renewal request
        kwargs = {'headers': headers}
        if data:
            kwargs['data'] = data
        if json_payload:
            kwargs['json'] = json_payload
        
        response = await client.request(method, endpoint, **kwargs)
        
        if response.status_code in (200, 201):
            result = response.json()
            logger.debug(f"KEYCHAIN: Renewal response: {result}")
            
            # Extract token data based on token_field
            # Support both flat structure and nested structure
            if token_field in result:
                # Return full response as token_data
                return result
            elif 'data' in result and isinstance(result['data'], dict):
                # Handle wrapped response
                return result['data']
            else:
                # Return entire response
                return result
        else:
            logger.error(
                f"KEYCHAIN: Token renewal failed for '{keychain_name}' - "
                f"HTTP {response.status_code}: {response.text}"
            )
            return None
            
    except Exception as e:
        logger.error(f"KEYCHAIN: Exception during token renewal for '{keychain_name}': {e}")
        return None


async def _update_keychain_entry(
    keychain_name: str,
    catalog_id: int,
    token_data: Dict[str, Any],
    renew_config: Dict[str, Any],
    api_base_url: str,
    client: httpx.AsyncClient
) -> bool:
    """
    Update keychain entry with renewed token.
    
    Args:
        keychain_name: Name of the keychain entry
        catalog_id: Catalog ID
        token_data: Renewed token data
        renew_config: Renewal configuration (to preserve for future renewals)
        api_base_url: Base URL of NoETL API
        client: HTTP client to use
        
    Returns:
        True if update successful, False otherwise
    """
    try:
        # Calculate TTL from token response
        ttl_seconds = None
        ttl_field = renew_config.get('ttl_field', 'expires_in')
        
        if ttl_field in token_data:
            ttl_seconds = int(token_data[ttl_field])
        elif 'expires_in' in token_data:
            ttl_seconds = int(token_data['expires_in'])
        else:
            # Default TTL: 1 hour
            ttl_seconds = 3600
        
        # Build update request
        url = f"{api_base_url}/api/keychain/{catalog_id}/{keychain_name}"
        payload = {
            "token_data": token_data,
            "credential_type": "oauth2_client_credentials",
            "cache_type": "token",
            "scope_type": "global",
            "ttl_seconds": ttl_seconds,
            "auto_renew": True,
            "renew_config": renew_config
        }
        
        logger.debug(f"KEYCHAIN: Updating '{keychain_name}' with renewed token (TTL: {ttl_seconds}s)")
        
        response = await client.post(url, json=payload)
        
        if response.status_code in (200, 201):
            logger.info(f"KEYCHAIN: Successfully updated '{keychain_name}' after renewal")
            return True
        else:
            logger.error(
                f"KEYCHAIN: Failed to update '{keychain_name}' - "
                f"HTTP {response.status_code}: {response.text}"
            )
            return False
            
    except Exception as e:
        logger.error(f"KEYCHAIN: Exception updating '{keychain_name}': {e}")
        return False


def extract_keychain_references(template_str: str) -> Set[str]:
    """
    Extract keychain reference names from a template string.
    
    Extracts names from patterns like:
    - {{ keychain.amadeus_token }}
    - {{ keychain.amadeus_token.access_token }}
    - {{ keychain.openai_token.api_key }}
    
    Args:
        template_str: Template string to scan
        
    Returns:
        Set of keychain entry names (e.g., {'amadeus_token', 'openai_token'})
    """
    if not isinstance(template_str, str):
        return set()
    
    # Match {{ keychain.name }} or {{ keychain.name.field }}
    pattern = r'\{\{\s*keychain\.(\w+)'
    matches = re.findall(pattern, template_str)
    return set(matches)


def extract_keychain_references_from_dict(data: Any) -> Set[str]:
    """
    Recursively extract keychain references from a dictionary or list.
    
    Args:
        data: Dictionary, list, or primitive value to scan
        
    Returns:
        Set of keychain entry names
    """
    refs = set()
    
    if isinstance(data, dict):
        for value in data.values():
            refs.update(extract_keychain_references_from_dict(value))
    elif isinstance(data, list):
        for item in data:
            refs.update(extract_keychain_references_from_dict(item))
    elif isinstance(data, str):
        refs.update(extract_keychain_references(data))
    
    return refs


async def resolve_keychain_entries(
    keychain_refs: Set[str],
    catalog_id: int,
    execution_id: Optional[int] = None,
    api_base_url: str = "http://noetl.noetl.svc.cluster.local:8082",
    refresh_threshold_seconds: int = 300
) -> Dict[str, Any]:
    """
    Resolve keychain entries by calling the keychain API.
    
    Automatically refreshes tokens that are expired or expiring soon to avoid
    tool execution failures due to expired credentials.
    
    Args:
        keychain_refs: Set of keychain entry names to resolve
        catalog_id: Catalog ID of the playbook
        execution_id: Optional execution ID for local scope
        api_base_url: Base URL of the NoETL API
        refresh_threshold_seconds: Refresh token if TTL is below this threshold (default: 300s = 5min)
        
    Returns:
        Dictionary mapping keychain names to their data
        Example: {'amadeus_token': {'access_token': '...', 'token_type': 'Bearer'}}
    """
    if not keychain_refs:
        return {}
    
    resolved = {}
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        for keychain_name in keychain_refs:
            try:
                # Build API URL
                url = f"{api_base_url}/api/keychain/{catalog_id}/{keychain_name}"
                
                # Try global scope first (most keychains are global)
                # Global: cache_key = {name}:{catalog_id}:global
                # Local: cache_key = {name}:{catalog_id}:{execution_id}
                params = {'scope_type': 'global'}
                
                print(f"[KEYCHAIN-RESOLVE] Calling {url} with params {params}")
                logger.info(f"KEYCHAIN: Resolving '{keychain_name}' from {url} (scope=global)")
                
                # Call keychain API
                response = await client.get(url, params=params)
                print(f"[KEYCHAIN-RESOLVE] Response status: {response.status_code}, body: {response.text[:500]}")
                
                if response.status_code == 200:
                    result = response.json()
                    
                    if result.get('status') == 'success' and result.get('token_data'):
                        ttl_seconds = result.get('ttl_seconds')
                        auto_renew = result.get('auto_renew', False)
                        renew_config = result.get('renew_config')
                        
                        # Check if token is expiring soon
                        needs_refresh = False
                        if ttl_seconds is not None:
                            if ttl_seconds <= 0:
                                logger.warning(
                                    f"KEYCHAIN: Token '{keychain_name}' is expired (TTL: {ttl_seconds}s)"
                                )
                                needs_refresh = True
                            elif ttl_seconds < refresh_threshold_seconds:
                                logger.warning(
                                    f"KEYCHAIN: Token '{keychain_name}' expiring soon "
                                    f"(TTL: {ttl_seconds}s < threshold: {refresh_threshold_seconds}s)"
                                )
                                needs_refresh = True
                            else:
                                logger.info(
                                    f"KEYCHAIN: Token '{keychain_name}' is valid (TTL: {ttl_seconds}s)"
                                )
                        
                        # Refresh token if needed and auto-renewal is configured
                        if needs_refresh and auto_renew and renew_config:
                            logger.info(f"KEYCHAIN: Proactively refreshing '{keychain_name}' before use")
                            renewed_data = await _renew_token(
                                keychain_name=keychain_name,
                                renew_config=renew_config,
                                client=client
                            )
                            
                            if renewed_data:
                                # Store renewed token back to keychain
                                await _update_keychain_entry(
                                    keychain_name=keychain_name,
                                    catalog_id=catalog_id,
                                    token_data=renewed_data,
                                    renew_config=renew_config,
                                    api_base_url=api_base_url,
                                    client=client
                                )
                                resolved[keychain_name] = renewed_data
                                logger.info(f"KEYCHAIN: Successfully refreshed '{keychain_name}' (was expiring soon)")
                            else:
                                logger.error(
                                    f"KEYCHAIN: Failed to refresh '{keychain_name}', "
                                    f"using existing token (may be expired)"
                                )
                                resolved[keychain_name] = result['token_data']
                        else:
                            # Token is valid or auto-renewal not configured
                            resolved[keychain_name] = result['token_data']
                            logger.info(f"KEYCHAIN: Resolved '{keychain_name}' successfully")
                            
                    elif result.get('status') == 'expired':
                        logger.warning(
                            f"KEYCHAIN: Entry '{keychain_name}' expired. "
                            f"Auto-renewal: {result.get('auto_renew', False)}"
                        )
                        
                        # Attempt auto-renewal if enabled
                        if result.get('auto_renew') and result.get('renew_config'):
                            logger.info(f"KEYCHAIN: Attempting auto-renewal for expired '{keychain_name}'")
                            renewed_data = await _renew_token(
                                keychain_name=keychain_name,
                                renew_config=result['renew_config'],
                                client=client
                            )
                            
                            if renewed_data:
                                # Store renewed token back to keychain
                                await _update_keychain_entry(
                                    keychain_name=keychain_name,
                                    catalog_id=catalog_id,
                                    token_data=renewed_data,
                                    renew_config=result['renew_config'],
                                    api_base_url=api_base_url,
                                    client=client
                                )
                                resolved[keychain_name] = renewed_data
                                logger.info(f"KEYCHAIN: Successfully renewed expired '{keychain_name}'")
                            else:
                                logger.error(f"KEYCHAIN: Failed to renew '{keychain_name}', returning empty dict")
                                resolved[keychain_name] = {}
                        else:
                            logger.warning(f"KEYCHAIN: Auto-renewal not configured for '{keychain_name}'")
                            resolved[keychain_name] = {}
                    elif result.get('status') == 'not_found':
                        # Try local scope as fallback if execution_id available
                        if execution_id:
                            logger.info(f"KEYCHAIN: '{keychain_name}' not found in global scope, trying local")
                            local_params = {'scope_type': 'local', 'execution_id': execution_id}
                            local_response = await client.get(url, params=local_params)
                            
                            if local_response.status_code == 200:
                                local_result = local_response.json()
                                if local_result.get('status') == 'success' and local_result.get('token_data'):
                                    resolved[keychain_name] = local_result['token_data']
                                    logger.info(f"KEYCHAIN: Resolved '{keychain_name}' from local scope")
                                    continue
                        
                        logger.warning(f"KEYCHAIN: Entry '{keychain_name}' not found in any scope")
                        resolved[keychain_name] = {}
                    else:
                        logger.error(f"KEYCHAIN: Unexpected status for '{keychain_name}': {result.get('status')}")
                        resolved[keychain_name] = {}
                else:
                    logger.error(
                        f"KEYCHAIN: Failed to resolve '{keychain_name}' - "
                        f"HTTP {response.status_code}: {response.text}"
                    )
                    resolved[keychain_name] = {}
                    
            except Exception as e:
                logger.error(f"KEYCHAIN: Error resolving '{keychain_name}': {e}")
                resolved[keychain_name] = {}
    
    return resolved


async def populate_keychain_context(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    catalog_id: int,
    execution_id: Optional[int] = None,
    api_base_url: str = "http://noetl.noetl.svc.cluster.local:8082",
    refresh_threshold_seconds: int = 300
) -> Dict[str, Any]:
    """
    Scan task config for keychain references and populate context.keychain.
    
    This function:
    1. Scans the task_config for {{ keychain.* }} references
    2. Resolves those keychain entries via API (with proactive token refresh)
    3. Adds them to context['keychain']
    
    Args:
        task_config: Task configuration dictionary
        context: Execution context dictionary (will be modified)
        catalog_id: Catalog ID of the playbook
        execution_id: Optional execution ID
        api_base_url: Base URL of NoETL API
        refresh_threshold_seconds: Refresh token if TTL is below this threshold (default: 300s = 5min)
        
    Returns:
        Updated context with 'keychain' attribute
    """
    # Extract all keychain references from task config
    keychain_refs = extract_keychain_references_from_dict(task_config)
    
    if not keychain_refs:
        logger.debug("KEYCHAIN: No keychain references found in task config")
        return context
    
    print(f"[KEYCHAIN-WORKER] Found {len(keychain_refs)} keychain references: {keychain_refs}")
    print(f"[KEYCHAIN-WORKER] catalog_id={catalog_id}, execution_id={execution_id}, api_base_url={api_base_url}")
    logger.info(f"KEYCHAIN: Found {len(keychain_refs)} keychain references: {keychain_refs}")
    
    # Resolve keychain entries with proactive refresh
    keychain_data = await resolve_keychain_entries(
        keychain_refs=keychain_refs,
        catalog_id=catalog_id,
        execution_id=execution_id,
        api_base_url=api_base_url,
        refresh_threshold_seconds=refresh_threshold_seconds
    )
    
    print(f"[KEYCHAIN-WORKER] Resolved keychain_data keys: {list(keychain_data.keys())}")
    print(f"[KEYCHAIN-WORKER] Resolved data: {keychain_data}")
    
    # Add to context
    context['keychain'] = keychain_data
    logger.info(f"KEYCHAIN: Populated context with {len(keychain_data)} keychain entries")
    
    return context
