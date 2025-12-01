"""
Credential and Token Cache Service for NoETL Workers.

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

Backend: PostgreSQL (noetl.auth_cache table)
Future: Support NATS KV or ValKey for distributed caching
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Any
from datetime import datetime, timedelta, timezone

import httpx
from noetl.core.config import get_worker_settings
from noetl.core.common import get_async_db_connection
from noetl.core.secret import encrypt_json, decrypt_json

logger = logging.getLogger(__name__)


class CredentialCache:
    """Credential and token caching service."""
    
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
            execution_id: Execution ID for execution-scoped cache
            token_type: Token type for global-scoped cache (e.g., 'oauth', 'jwt')
            
        Returns:
            Cache key string
        """
        if execution_id:
            return f"{credential_name}:{execution_id}"
        elif token_type:
            return f"{credential_name}:global:{token_type}"
        else:
            raise ValueError("Either execution_id or token_type must be provided")
    
    @staticmethod
    async def get_cached(
        credential_name: str,
        execution_id: Optional[int] = None,
        token_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached credential or token.
        
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
        
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    # Fetch and update access tracking
                    await cursor.execute(
                        """
                        UPDATE noetl.auth_cache
                        SET accessed_at = now(),
                            access_count = access_count + 1
                        WHERE cache_key = %s
                          AND expires_at > now()
                        RETURNING data_encrypted, credential_type, cache_type
                        """,
                        (cache_key,)
                    )
                    row = await cursor.fetchone()
                    
                    if not row:
                        logger.debug(f"Cache miss for key: {cache_key}")
                        return None
                    
                    # Decrypt and return
                    encrypted_data, cred_type, cache_type = row
                    decrypted = decrypt_json(encrypted_data)
                    
                    logger.info(
                        f"Cache hit for {cache_type} '{credential_name}' "
                        f"({'execution' if execution_id else 'global'} scope)"
                    )
                    
                    return {
                        'credential_name': credential_name,
                        'credential_type': cred_type,
                        'cache_type': cache_type,
                        'data': decrypted
                    }
                    
        except Exception as e:
            logger.error(f"Error retrieving from cache: {e}")
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
        Store credential or token in cache.
        
        Args:
            credential_name: Name of the credential
            credential_type: Type of credential (postgres, google_oauth, etc.)
            data: Credential data to cache (will be encrypted)
            cache_type: 'secret' or 'token'
            execution_id: Execution ID for execution-scoped cache
            parent_execution_id: Parent execution ID for cleanup tracking
            token_type: Token type for global-scoped cache
            ttl_seconds: TTL in seconds (used if expires_at not provided)
            expires_at: Explicit expiration timestamp
            
        Returns:
            True if successfully cached, False otherwise
        """
        # Determine scope
        if execution_id:
            scope_type = 'execution'
            cache_key = CredentialCache._make_cache_key(credential_name, execution_id=execution_id)
        elif token_type:
            scope_type = 'global'
            cache_key = CredentialCache._make_cache_key(credential_name, token_type=token_type)
        else:
            raise ValueError("Either execution_id or token_type must be provided")
        
        # Calculate expiration
        if expires_at is None:
            if ttl_seconds is None:
                # Default TTL: 1 hour for execution scope, 24 hours for global
                ttl_seconds = 3600 if scope_type == 'execution' else 86400
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        
        # Encrypt data
        try:
            encrypted_data = encrypt_json(data)
        except Exception as e:
            logger.error(f"Failed to encrypt cache data: {e}")
            return False
        
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO noetl.auth_cache (
                            cache_key, credential_name, credential_type, cache_type,
                            scope_type, execution_id, parent_execution_id,
                            data_encrypted, expires_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (cache_key) DO UPDATE SET
                            data_encrypted = EXCLUDED.data_encrypted,
                            expires_at = EXCLUDED.expires_at,
                            accessed_at = now(),
                            access_count = 0
                        """,
                        (
                            cache_key, credential_name, credential_type, cache_type,
                            scope_type, execution_id, parent_execution_id,
                            encrypted_data, expires_at
                        )
                    )
                    try:
                        await conn.commit()
                    except Exception as e:
                        logger.warning(f"Commit warning (may auto-commit): {e}")
            
            logger.info(
                f"Cached {cache_type} '{credential_name}' "
                f"({scope_type} scope, expires: {expires_at})"
            )
            return True
            
        except Exception as e:
            logger.error(f"Failed to cache credential: {e}")
            return False
    
    @staticmethod
    async def cleanup_execution(execution_id: int, parent_execution_id: Optional[int] = None):
        """
        Clean up execution-scoped cache entries.
        
        Called when a playbook execution completes.
        
        Args:
            execution_id: Execution ID to clean up
            parent_execution_id: Parent execution ID for hierarchical cleanup
        """
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    # Delete entries for this execution or its parent
                    await cursor.execute(
                        """
                        DELETE FROM noetl.auth_cache
                        WHERE scope_type = 'execution'
                          AND (execution_id = %s OR parent_execution_id = %s)
                        """,
                        (execution_id, parent_execution_id or execution_id)
                    )
                    deleted = cursor.rowcount
                    
                    if deleted > 0:
                        logger.info(
                            f"Cleaned up {deleted} cached credential(s) for execution {execution_id}"
                        )
                    
                    try:
                        await conn.commit()
                    except Exception as e:
                        logger.warning(f"Commit warning (may auto-commit): {e}")
                        
        except Exception as e:
            logger.error(f"Failed to cleanup execution cache: {e}")
    
    @staticmethod
    async def cleanup_expired():
        """
        Clean up expired cache entries (both execution and global scoped).
        
        Should be called periodically by a background task.
        """
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        DELETE FROM noetl.auth_cache
                        WHERE expires_at < now()
                        """
                    )
                    deleted = cursor.rowcount
                    
                    if deleted > 0:
                        logger.info(f"Cleaned up {deleted} expired cache entries")
                    
                    try:
                        await conn.commit()
                    except Exception as e:
                        logger.warning(f"Commit warning (may auto-commit): {e}")
                        
        except Exception as e:
            logger.error(f"Failed to cleanup expired cache: {e}")


async def fetch_credential_with_cache(
    credential_name: str,
    execution_id: Optional[int] = None,
    parent_execution_id: Optional[int] = None,
    cache_ttl: Optional[int] = None
) -> Dict[str, Any]:
    """
    Fetch credential with automatic caching.
    
    Workflow:
    1. Check cache first
    2. If miss, fetch from server
    3. Store in cache for subsequent requests
    
    Args:
        credential_name: Name of the credential to fetch
        execution_id: Current execution ID (for execution-scoped caching)
        parent_execution_id: Parent execution ID (for cleanup tracking)
        cache_ttl: Custom TTL in seconds (optional)
        
    Returns:
        Credential data dictionary
        
    Raises:
        Exception: If credential cannot be fetched
    """
    # Try cache first (only if execution_id provided for execution scope)
    if execution_id:
        cached = await CredentialCache.get_cached(
            credential_name,
            execution_id=execution_id
        )
        if cached:
            return cached['data']
    
    # Cache miss - fetch from server
    logger.debug(f"Fetching credential '{credential_name}' from server")
    
    try:
        worker_settings = get_worker_settings()
        url = worker_settings.endpoint_credential_by_key(credential_name, include_data=True)
    except Exception:
        url = f"http://localhost:8082/api/credentials/{credential_name}?include_data=true"
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            
            body = response.json() or {}
            data = body.get('data') or {}
            credential_type = body.get('type') or body.get('credential_type') or 'generic'
            
            # Store in cache if execution_id provided
            if execution_id and isinstance(data, dict):
                await CredentialCache.set_cached(
                    credential_name=credential_name,
                    credential_type=credential_type,
                    data=data,
                    cache_type='secret',
                    execution_id=execution_id,
                    parent_execution_id=parent_execution_id,
                    ttl_seconds=cache_ttl
                )
            
            return data
            
    except Exception as e:
        logger.error(f"Failed to fetch credential '{credential_name}': {e}")
        raise


async def store_token_in_cache(
    credential_name: str,
    token_data: Dict[str, Any],
    token_type: str = 'oauth',
    credential_type: str = 'token',
    expires_in_seconds: Optional[int] = None,
    expires_at: Optional[datetime] = None
) -> bool:
    """
    Store authentication token in global cache.
    
    Args:
        credential_name: Name/identifier for the token
        token_data: Token payload (access_token, refresh_token, etc.)
        token_type: Type of token (oauth, jwt, bearer, etc.)
        credential_type: Credential type for tracking
        expires_in_seconds: Token expiration in seconds
        expires_at: Explicit expiration timestamp
        
    Returns:
        True if successfully cached
    """
    return await CredentialCache.set_cached(
        credential_name=credential_name,
        credential_type=credential_type,
        data=token_data,
        cache_type='token',
        token_type=token_type,
        ttl_seconds=expires_in_seconds,
        expires_at=expires_at
    )


async def get_token_from_cache(
    credential_name: str,
    token_type: str = 'oauth'
) -> Optional[Dict[str, Any]]:
    """
    Retrieve authentication token from global cache.
    
    Args:
        credential_name: Name/identifier for the token
        token_type: Type of token (oauth, jwt, bearer, etc.)
        
    Returns:
        Token data or None if not found/expired
    """
    cached = await CredentialCache.get_cached(
        credential_name,
        token_type=token_type
    )
    return cached['data'] if cached else None


__all__ = [
    'CredentialCache',
    'fetch_credential_with_cache',
    'store_token_in_cache',
    'get_token_from_cache'
]
