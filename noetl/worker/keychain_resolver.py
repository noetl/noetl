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
    api_base_url: str = "http://noetl.noetl.svc.cluster.local:8080"
) -> Dict[str, Any]:
    """
    Resolve keychain entries by calling the keychain API.
    
    Args:
        keychain_refs: Set of keychain entry names to resolve
        catalog_id: Catalog ID of the playbook
        execution_id: Optional execution ID for local scope
        api_base_url: Base URL of the NoETL API
        
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
                params = {}
                if execution_id:
                    params['execution_id'] = execution_id
                
                logger.debug(f"KEYCHAIN: Resolving '{keychain_name}' from {url}")
                
                # Call keychain API
                response = await client.get(url, params=params)
                
                if response.status_code == 200:
                    result = response.json()
                    
                    if result.get('status') == 'success' and result.get('token_data'):
                        resolved[keychain_name] = result['token_data']
                        logger.info(f"KEYCHAIN: Resolved '{keychain_name}' successfully")
                    elif result.get('status') == 'expired':
                        logger.warning(
                            f"KEYCHAIN: Entry '{keychain_name}' expired. "
                            f"Auto-renewal: {result.get('auto_renew', False)}"
                        )
                        # TODO: Implement auto-renewal logic
                        # For now, return empty dict to fail gracefully
                        resolved[keychain_name] = {}
                    elif result.get('status') == 'not_found':
                        logger.warning(f"KEYCHAIN: Entry '{keychain_name}' not found")
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
    api_base_url: str = "http://noetl.noetl.svc.cluster.local:8080"
) -> Dict[str, Any]:
    """
    Scan task config for keychain references and populate context.keychain.
    
    This function:
    1. Scans the task_config for {{ keychain.* }} references
    2. Resolves those keychain entries via API
    3. Adds them to context['keychain']
    
    Args:
        task_config: Task configuration dictionary
        context: Execution context dictionary (will be modified)
        catalog_id: Catalog ID of the playbook
        execution_id: Optional execution ID
        api_base_url: Base URL of NoETL API
        
    Returns:
        Updated context with 'keychain' attribute
    """
    # Extract all keychain references from task config
    keychain_refs = extract_keychain_references_from_dict(task_config)
    
    if not keychain_refs:
        logger.debug("KEYCHAIN: No keychain references found in task config")
        return context
    
    logger.info(f"KEYCHAIN: Found {len(keychain_refs)} keychain references: {keychain_refs}")
    
    # Resolve keychain entries
    keychain_data = await resolve_keychain_entries(
        keychain_refs=keychain_refs,
        catalog_id=catalog_id,
        execution_id=execution_id,
        api_base_url=api_base_url
    )
    
    # Add to context
    context['keychain'] = keychain_data
    logger.info(f"KEYCHAIN: Populated context with {len(keychain_data)} keychain entries")
    
    return context
