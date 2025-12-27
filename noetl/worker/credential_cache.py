"""
Credential and Token Cache API Client for NoETL Workers.

Provides two caching strategies:
1. Execution-scoped: Credentials cached for playbook execution and sub-playbooks
   - TTL: lifetime of parent execution
   - Cleanup: automatic when parent execution completes
   - Use case: API keys, passwords fetched from external secret managers

2. Global-scoped: Tokens shared across all executions
   - TTL: based on token expiration (from OAuth response, JWT exp, etc.)
   - Cleanup: automatic expiration
   - Use case: OAuth access tokens, service account tokens

Cache key format:
- Execution-scoped: {credential_name}:{execution_id}
- Global-scoped: {credential_name}:global:{token_type}

Backend: Server API (/api/auth-cache)
IMPORTANT: Workers NEVER access noetl schema directly - all operations via server API
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Any
from datetime import datetime, timedelta, timezone

import httpx
from noetl.core.config import get_worker_settings

from noetl.core.logger import setup_logger
logger = setup_logger(__name__, include_location=True)


class CredentialCache:
    """
    Credential and token caching API client for workers.
    
    All operations delegate to the server's auth_cache API.
    Workers do NOT access the database directly.
    """
    
    @staticmethod
    def _make_cache_key(
        credential_name: str,
        execution_id: Optional[int] = None,
        token_type: Optional[str] = None
    ) -> str:
        """
        Generate cache key based on scope.
        
        Args:
            credential_name: Name of the credential
            execution_id: Optional execution ID for execution-scoped cache
            token_type: Optional token type for global-scoped cache
            
        Returns:
            Cache key string
        """
        if execution_id:
            # Execution-scoped: {credential_name}:{execution_id}
            return f"{credential_name}:{execution_id}"
        elif token_type:
            # Global-scoped: {credential_name}:global:{token_type}
            return f"{credential_name}:global:{token_type}"
        else:
            # Global default: {credential_name}:global
            return f"{credential_name}:global"
    
    @staticmethod
    def _get_api_base_url() -> str:
        """Get the NoETL server API base URL."""
        settings = get_worker_settings()
        # Use the server URL from worker settings
        server_url = getattr(settings, 'server_url', 'http://noetl.noetl.svc.cluster.local:8080')
        return f"{server_url}/api/auth-cache"
    
    @staticmethod
    async def get_cached(
        credential_name: str,
        execution_id: Optional[int] = None,
        token_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached credential or token via server API.
        
        Args:
            credential_name: Name of the credential
            execution_id: Execution ID for execution-scoped lookup
            token_type: Token type for global-scoped lookup
            
        Returns:
            Decrypted credential data or None if not found/expired
        """
        cache_key = CredentialCache._make_cache_key(
            credential_name,
            execution_id=execution_id,
            token_type=token_type
        )
        
        api_base = CredentialCache._get_api_base_url()
        api_url = f"{api_base}/{cache_key}"
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(api_url)
                
                if response.status_code == 404:
                    logger.debug(f"Cache miss for key: {cache_key}")
                    return None
                
                if response.status_code != 200:
                    logger.error(f"Auth cache API error: {response.status_code} - {response.text}")
                    return None
                
                data = response.json()
                logger.info(
                    f"Cache hit for {data.get('cache_type', 'unknown')} '{credential_name}' "
                    f"({'execution' if execution_id else 'global'} scope)"
                )
                
                # Return the decrypted data from API response
                return {
                    'credential_name': credential_name,
                    'data': data.get('data', {}),
                    'credential_type': data.get('credential_type'),
                    'cache_type': data.get('cache_type'),
                    'expires_at': data.get('expires_at')
                }
                
        except httpx.RequestError as e:
            logger.error(f"Failed to retrieve cached credential {cache_key}: {e}")
            return None
    
    @staticmethod
    async def set_cached(
        credential_name: str,
        credential_type: str,
        data: Dict[str, Any],
        cache_type: str = 'secret',
        execution_id: Optional[int] = None,
        parent_execution_id: Optional[int] = None,
        token_type: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        expires_at: Optional[datetime] = None
    ) -> bool:
        """
        Store credential or token in cache via server API.
        
        Args:
            credential_name: Name of the credential
            credential_type: Type of credential (postgres, google_oauth, etc.)
            data: Credential data to cache (will be encrypted)
            cache_type: 'secret' or 'token'
            execution_id: Execution ID for execution-scoped cache
            parent_execution_id: Parent execution ID for sub-playbook scoping
            token_type: Token type for global-scoped cache (e.g., 'oauth2', 'jwt')
            ttl_seconds: Time-to-live in seconds (default: 3600 for secrets, 7 days for global tokens)
            expires_at: Explicit expiration datetime (overrides ttl_seconds)
            
        Returns:
            True if cached successfully, False otherwise
        """
        cache_key = CredentialCache._make_cache_key(
            credential_name,
            execution_id=execution_id or parent_execution_id,
            token_type=token_type
        )
        
        # Determine scope type
        if execution_id or parent_execution_id:
            scope_type = 'local'
        elif token_type:
            scope_type = 'global'
        else:
            scope_type = 'shared'
        
        # Calculate TTL if not provided
        if not ttl_seconds and not expires_at:
            if scope_type == 'local':
                ttl_seconds = 3600  # 1 hour for execution-scoped
            else:
                ttl_seconds = 604800  # 7 days for global tokens
        
        api_base = CredentialCache._get_api_base_url()
        api_url = f"{api_base}/{cache_key}"
        
        payload = {
            'token_data': data,
            'credential_type': credential_type,
            'cache_type': cache_type,
            'scope_type': scope_type,
            'ttl_seconds': ttl_seconds,
        }
        
        if execution_id:
            payload['execution_id'] = execution_id
        if parent_execution_id:
            payload['parent_execution_id'] = parent_execution_id
        if expires_at:
            payload['expires_at'] = expires_at.isoformat() if isinstance(expires_at, datetime) else expires_at
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(api_url, json=payload)
                
                if response.status_code == 200:
                    logger.info(
                        f"Cached {cache_type} '{credential_name}' "
                        f"({scope_type} scope, TTL: {ttl_seconds}s)"
                    )
                    return True
                else:
                    logger.error(f"Auth cache API error: {response.status_code} - {response.text}")
                    return False
                    
        except httpx.RequestError as e:
            logger.error(f"Failed to cache credential {cache_key}: {e}")
            return False
    
    @staticmethod
    async def delete_cached(
        credential_name: str,
        execution_id: Optional[int] = None,
        token_type: Optional[str] = None
    ) -> bool:
        """
        Delete cached credential or token via server API.
        
        Args:
            credential_name: Name of the credential
            execution_id: Execution ID for execution-scoped deletion
            token_type: Token type for global-scoped deletion
            
        Returns:
            True if deleted successfully, False otherwise
        """
        cache_key = CredentialCache._make_cache_key(
            credential_name,
            execution_id=execution_id,
            token_type=token_type
        )
        
        api_base = CredentialCache._get_api_base_url()
        api_url = f"{api_base}/{cache_key}"
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.delete(api_url)
                
                if response.status_code in (200, 204):
                    logger.info(f"Deleted cached credential: {cache_key}")
                    return True
                elif response.status_code == 404:
                    logger.debug(f"No cached credential to delete: {cache_key}")
                    return True  # Consider as success
                else:
                    logger.error(f"Auth cache API error: {response.status_code} - {response.text}")
                    return False
                    
        except httpx.RequestError as e:
            logger.error(f"Failed to delete cached credential {cache_key}: {e}")
            return False
    
    @staticmethod
    async def cleanup_execution(execution_id: int) -> int:
        """
        Clean up all execution-scoped cached credentials via server API.
        
        This is not directly supported by the current API, so we return 0.
        Cleanup should be handled by server-side TTL expiration.
        
        Args:
            execution_id: Execution ID to clean up
            
        Returns:
            Number of entries deleted (always 0 for now)
        """
        logger.info(f"Execution {execution_id} cleanup delegated to server-side TTL expiration")
        return 0
    
    @staticmethod
    async def cleanup_expired() -> int:
        """
        Clean up expired cache entries via server API.
        
        This is not directly supported by the current API, so we return 0.
        Cleanup should be handled by server-side background tasks.
        
        Returns:
            Number of entries deleted (always 0 for now)
        """
        logger.info("Expired cleanup delegated to server-side background tasks")
        return 0
