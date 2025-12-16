"""
Keychain Service Layer.

Provides server-side database operations for keychain management.
This service layer directly accesses the noetl.keychain table.

IMPORTANT: Only server-side code should use this service.
Workers must use the REST API endpoints instead.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Any
from datetime import datetime, timedelta, timezone

from noetl.core.common import get_async_db_connection
from noetl.core.secret import encrypt_json, decrypt_json

logger = logging.getLogger(__name__)


class KeychainService:
    """
    Server-side keychain service.
    
    Handles all database operations for keychain table.
    Workers must NOT use this - they should call REST API instead.
    """
    
    @staticmethod
    def _make_cache_key(
        keychain_name: str,
        catalog_id: int,
        execution_id: Optional[int] = None,
        scope_type: str = 'global'
    ) -> str:
        """Generate cache key for keychain entry."""
        if scope_type == 'local' and execution_id:
            return f"{keychain_name}:{catalog_id}:{execution_id}"
        elif scope_type == 'shared' and execution_id:
            return f"{keychain_name}:{catalog_id}:shared:{execution_id}"
        else:
            return f"{keychain_name}:{catalog_id}:global"
    
    @staticmethod
    async def get_keychain_entry(
        keychain_name: str,
        catalog_id: int,
        execution_id: Optional[int] = None,
        scope_type: str = 'global'
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve keychain entry from database.
        
        Updates access_count and accessed_at timestamp.
        Handles expired tokens with auto_renew flag.
        
        Args:
            keychain_name: Name of keychain entry
            catalog_id: Catalog ID of the playbook
            execution_id: Optional execution ID for local scope
            scope_type: Scope type (local, global, shared)
            
        Returns:
            Keychain data with metadata or None if not found/expired
        """
        cache_key = KeychainService._make_cache_key(
            keychain_name, catalog_id, execution_id, scope_type
        )
        
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    # Fetch and update access tracking
                    await cursor.execute(
                        """
                        UPDATE noetl.keychain
                        SET accessed_at = now(),
                            access_count = access_count + 1
                        WHERE cache_key = %s
                          AND expires_at > now()
                        RETURNING keychain_name, catalog_id, data_encrypted, credential_type, 
                                  cache_type, execution_id, parent_execution_id, scope_type,
                                  expires_at, created_at, accessed_at, access_count,
                                  auto_renew, renew_config
                        """,
                        (cache_key,)
                    )
                    row = await cursor.fetchone()
                    
                    if not row:
                        # Check if expired entry exists with auto_renew
                        await cursor.execute(
                            """
                            SELECT keychain_name, catalog_id, auto_renew, renew_config, expires_at
                            FROM noetl.keychain
                            WHERE cache_key = %s AND expires_at <= now()
                            """,
                            (cache_key,)
                        )
                        expired_row = await cursor.fetchone()
                        
                        if expired_row and expired_row[2]:  # auto_renew is True
                            logger.info(f"Token expired for {keychain_name}, auto_renew enabled")
                            renew_cfg = decrypt_json(expired_row[3]) if expired_row[3] else None
                            return {
                                'keychain_name': expired_row[0],
                                'catalog_id': expired_row[1],
                                'expired': True,
                                'auto_renew': True,
                                'renew_config': renew_cfg,
                                'cache_key': cache_key
                            }
                        
                        logger.debug(f"Cache miss for key: {cache_key}")
                        return None
                    
                    # Decrypt and return
                    (kc_name, cat_id, encrypted_data, cred_type, cache_type, 
                     exec_id, parent_exec_id, sc_type, expires_at, created_at, 
                     accessed_at, access_count, auto_renew, renew_config_encrypted) = row
                    
                    decrypted = decrypt_json(encrypted_data)
                    renew_cfg = decrypt_json(renew_config_encrypted) if renew_config_encrypted else None
                    
                    logger.info(f"Cache hit for {cache_type} keychain: {keychain_name}")
                    
                    return {
                        'keychain_name': kc_name,
                        'catalog_id': cat_id,
                        'cache_key': cache_key,
                        'data': decrypted,
                        'credential_type': cred_type,
                        'cache_type': cache_type,
                        'execution_id': exec_id,
                        'parent_execution_id': parent_exec_id,
                        'scope_type': sc_type,
                        'expires_at': expires_at,
                        'created_at': created_at,
                        'accessed_at': accessed_at,
                        'access_count': access_count,
                        'auto_renew': auto_renew,
                        'renew_config': renew_cfg,
                        'expired': False
                    }
                    
        except Exception as e:
            logger.error(f"Error retrieving keychain entry {keychain_name}: {e}")
            return None
    
    @staticmethod
    async def set_keychain_entry(
        keychain_name: str,
        catalog_id: int,
        token_data: Dict[str, Any],
        credential_type: str,
        cache_type: str = 'token',
        scope_type: str = 'global',
        execution_id: Optional[int] = None,
        parent_execution_id: Optional[int] = None,
        ttl_seconds: Optional[int] = None,
        expires_at: Optional[datetime] = None,
        auto_renew: bool = False,
        renew_config: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Store keychain entry in cache database.
        
        Args:
            keychain_name: Name of keychain entry
            catalog_id: Catalog ID of the playbook
            token_data: Token/credential data to cache (will be encrypted)
            credential_type: Type of credential (oauth2_client_credentials, etc.)
            cache_type: 'secret' or 'token'
            scope_type: 'local', 'global', or 'shared'
            execution_id: Optional execution ID for local scope
            parent_execution_id: Optional parent execution ID
            ttl_seconds: Time-to-live in seconds
            expires_at: Explicit expiration datetime (overrides ttl_seconds)
            auto_renew: If True, automatically renew token when expired
            renew_config: Configuration for automatic renewal
            
        Returns:
            True if cached successfully, False otherwise
        """
        cache_key = KeychainService._make_cache_key(
            keychain_name, catalog_id, execution_id, scope_type
        )
        
        try:
            # Calculate expiration
            if expires_at is None:
                if ttl_seconds is None:
                    ttl_seconds = 3600 if scope_type == 'local' else 604800
                expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
            elif isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            
            # Ensure timezone aware
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            
            # Encrypt the data
            encrypted_data = encrypt_json(token_data)
            encrypted_renew_config = encrypt_json(renew_config) if renew_config else None
            
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO noetl.keychain (
                            cache_key, keychain_name, catalog_id, data_encrypted, 
                            credential_type, cache_type, execution_id, parent_execution_id, 
                            scope_type, expires_at, created_at, accessed_at, access_count,
                            auto_renew, renew_config
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now(), 0, %s, %s
                        )
                        ON CONFLICT (cache_key) DO UPDATE
                        SET data_encrypted = EXCLUDED.data_encrypted,
                            credential_type = EXCLUDED.credential_type,
                            cache_type = EXCLUDED.cache_type,
                            execution_id = EXCLUDED.execution_id,
                            parent_execution_id = EXCLUDED.parent_execution_id,
                            scope_type = EXCLUDED.scope_type,
                            expires_at = EXCLUDED.expires_at,
                            accessed_at = now(),
                            auto_renew = EXCLUDED.auto_renew,
                            renew_config = EXCLUDED.renew_config
                        """,
                        (
                            cache_key, keychain_name, catalog_id, encrypted_data,
                            credential_type, cache_type, execution_id, parent_execution_id,
                            scope_type, expires_at, auto_renew, encrypted_renew_config
                        )
                    )
                    await conn.commit()
                    
            logger.info(
                f"Cached {cache_type} keychain: {keychain_name} for catalog {catalog_id} "
                f"(scope: {scope_type}, expires: {expires_at}, auto_renew: {auto_renew})"
            )
            return True
                    
        except Exception as e:
            logger.error(f"Error caching keychain entry {keychain_name}: {e}")
            return False
    
    @staticmethod
    async def delete_keychain_entry(
        keychain_name: str,
        catalog_id: int,
        execution_id: Optional[int] = None,
        scope_type: str = 'global'
    ) -> bool:
        """Delete keychain entry from database."""
        cache_key = KeychainService._make_cache_key(
            keychain_name, catalog_id, execution_id, scope_type
        )
        
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "DELETE FROM noetl.keychain WHERE cache_key = %s",
                        (cache_key,)
                    )
                    await conn.commit()
                    
            logger.info(f"Deleted keychain entry: {keychain_name}")
            return True
                    
        except Exception as e:
            logger.error(f"Error deleting keychain entry {keychain_name}: {e}")
            return False
    
    @staticmethod
    async def cleanup_execution(execution_id: int) -> int:
        """Clean up all execution-scoped keychain entries."""
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "DELETE FROM noetl.keychain WHERE execution_id = %s OR parent_execution_id = %s",
                        (execution_id, execution_id)
                    )
                    count = cursor.rowcount
                    await conn.commit()
                    
            logger.info(f"Cleaned up {count} keychain entries for execution {execution_id}")
            return count
                    
        except Exception as e:
            logger.error(f"Error cleaning up execution keychain: {e}")
            return 0
    
    @staticmethod
    async def cleanup_expired() -> int:
        """Clean up expired keychain entries (excluding auto_renew entries)."""
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "DELETE FROM noetl.keychain WHERE expires_at <= now() AND auto_renew = false"
                    )
                    count = cursor.rowcount
                    await conn.commit()
                    
            logger.info(f"Cleaned up {count} expired keychain entries")
            return count
                    
        except Exception as e:
            logger.error(f"Error cleaning up expired keychain: {e}")
            return 0
    
    @staticmethod
    async def get_catalog_keychain_entries(catalog_id: int) -> list[Dict[str, Any]]:
        """Get all keychain entries for a specific catalog."""
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT keychain_name, cache_key, credential_type, cache_type,
                               scope_type, expires_at, auto_renew, access_count
                        FROM noetl.keychain
                        WHERE catalog_id = %s
                        ORDER BY keychain_name, scope_type
                        """,
                        (catalog_id,)
                    )
                    rows = await cursor.fetchall()
                    
                    return [
                        {
                            'keychain_name': row[0],
                            'cache_key': row[1],
                            'credential_type': row[2],
                            'cache_type': row[3],
                            'scope_type': row[4],
                            'expires_at': row[5],
                            'auto_renew': row[6],
                            'access_count': row[7]
                        }
                        for row in rows
                    ]
                    
        except Exception as e:
            logger.error(f"Error retrieving catalog keychain entries: {e}")
            return []
