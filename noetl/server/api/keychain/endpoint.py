"""
Keychain API endpoints.

Provides REST API for managing keychain entries:
- GET /api/keychain/{catalog_id}/{keychain_name} - Get keychain entry
- POST /api/keychain/{catalog_id}/{keychain_name} - Set/update keychain entry
- DELETE /api/keychain/{catalog_id}/{keychain_name} - Delete keychain entry
- GET /api/keychain/catalog/{catalog_id} - List all entries for catalog

These endpoints allow workflow steps to cache OAuth tokens, credentials,
and other authentication data for reuse across executions.

Backend: noetl.keychain table
"""

from typing import Optional
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Path, Body, Query

from .service import KeychainService
from noetl.core.logger import setup_logger
from .schema import (
    KeychainSetRequest,
    KeychainSetResponse,
    KeychainGetResponse,
    KeychainDeleteResponse,
    KeychainListResponse
)

logger = setup_logger(__name__, include_location=True)
router = APIRouter(prefix="/keychain", tags=["keychain"])


@router.get("/{catalog_id}/{keychain_name}", response_model=KeychainGetResponse)
async def get_keychain_entry(
    catalog_id: int = Path(..., description="Catalog ID of the playbook"),
    keychain_name: str = Path(..., description="Name of keychain entry (e.g., 'amadeus_token', 'postgres_creds')"),
    execution_id: Optional[int] = Query(None, description="Execution ID for local/shared scope"),
    scope_type: str = Query("global", description="Scope type: 'local', 'global', or 'shared'")
) -> KeychainGetResponse:
    """
    Get a keychain entry by catalog_id and keychain_name.
    
    Returns token/credential data with metadata if found and not expired.
    Increments access_count and updates accessed_at timestamp.
    
    Scope resolution:
    - local: {keychain_name}:{catalog_id}:{execution_id}
    - shared: {keychain_name}:{catalog_id}:shared:{execution_id}
    - global: {keychain_name}:{catalog_id}:global
    
    Returns status 'expired' if token exists but expired and auto_renew is enabled.
    Returns status 'not_found' if token not found.
    """
    try:
        # Retrieve from keychain
        entry = await KeychainService.get_keychain_entry(
            keychain_name=keychain_name,
            catalog_id=catalog_id,
            execution_id=execution_id,
            scope_type=scope_type
        )
        
        if entry is None:
            logger.warning(f"API: Keychain entry not found: {keychain_name} (catalog: {catalog_id})")
            return KeychainGetResponse(
                status="not_found",
                keychain_name=keychain_name,
                catalog_id=catalog_id,
                cache_key=KeychainService._make_cache_key(keychain_name, catalog_id, execution_id, scope_type)
            )
        
        # Handle expired with auto_renew
        if entry.get('expired') and entry.get('auto_renew'):
            logger.info(f"API: Keychain entry expired with auto_renew: {keychain_name}")
            return KeychainGetResponse(
                status="expired",
                keychain_name=entry['keychain_name'],
                catalog_id=entry['catalog_id'],
                cache_key=entry['cache_key'],
                auto_renew=True,
                renew_config=entry.get('renew_config'),
                expired=True
            )
        
        # Calculate remaining TTL
        ttl_seconds = None
        if entry.get('expires_at'):
            expires_at = entry['expires_at']
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            ttl_seconds = (expires_at - datetime.now(timezone.utc)).total_seconds()
        
        logger.info(f"API: Retrieved keychain entry: {keychain_name} (catalog: {catalog_id})")
        
        return KeychainGetResponse(
            status="success",
            keychain_name=entry['keychain_name'],
            catalog_id=entry['catalog_id'],
            cache_key=entry['cache_key'],
            token_data=entry.get('data'),
            credential_type=entry.get('credential_type'),
            cache_type=entry.get('cache_type'),
            scope_type=entry.get('scope_type'),
            expires_at=entry.get('expires_at'),
            ttl_seconds=ttl_seconds,
            accessed_at=entry.get('accessed_at'),
            access_count=entry.get('access_count'),
            auto_renew=entry.get('auto_renew', False),
            renew_config=entry.get('renew_config'),
            expired=False
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API: Failed to get keychain entry {keychain_name}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve keychain entry: {str(e)}"
        )


@router.post("/{catalog_id}/{keychain_name}", response_model=KeychainSetResponse)
async def set_keychain_entry(
    catalog_id: int = Path(..., description="Catalog ID of the playbook"),
    keychain_name: str = Path(..., description="Name of keychain entry"),
    request: KeychainSetRequest = Body(...)
) -> KeychainSetResponse:
    """
    Cache a keychain entry with the specified catalog_id and keychain_name.
    
    Stores token/credential data with encryption in the keychain table.
    Supports local, global, and shared scoping.
    
    Scope types:
    - local: Limited to specific execution and its sub-playbooks
    - global: Shared across all executions until token expires
    - shared: Shared within execution tree (parent + children)
    
    Auto-renewal:
    - If auto_renew=true, system will automatically refresh token on expiration
    - renew_config must contain endpoint, method, and auth information
    """
    try:
        # Calculate expiration
        expires_at = request.expires_at
        ttl_seconds = request.ttl_seconds
        
        if expires_at is None and ttl_seconds is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        elif expires_at is None:
            # Default TTL: 1 hour for local, 24 hours for global
            default_ttl = 3600 if request.scope_type == 'local' else 86400
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=default_ttl)
            ttl_seconds = default_ttl
        
        # Calculate TTL if not provided
        if ttl_seconds is None and expires_at:
            ttl_seconds = int((expires_at - datetime.now(timezone.utc)).total_seconds())
        
        # Cache the entry using service layer
        success = await KeychainService.set_keychain_entry(
            keychain_name=keychain_name,
            catalog_id=catalog_id,
            token_data=request.token_data,
            credential_type=request.credential_type,
            cache_type=request.cache_type,
            scope_type=request.scope_type,
            execution_id=request.execution_id,
            parent_execution_id=request.parent_execution_id,
            ttl_seconds=ttl_seconds,
            expires_at=expires_at,
            auto_renew=request.auto_renew,
            renew_config=request.renew_config
        )
        
        if success:
            cache_key = KeychainService._make_cache_key(
                keychain_name, catalog_id, request.execution_id, request.scope_type
            )
            logger.info(
                f"API: Cached keychain entry: {keychain_name} for catalog {catalog_id} "
                f"(scope={request.scope_type}, ttl={ttl_seconds}s, auto_renew={request.auto_renew})"
            )
            return KeychainSetResponse(
                status="success",
                message=f"Keychain entry cached successfully with {ttl_seconds}s TTL",
                keychain_name=keychain_name,
                catalog_id=catalog_id,
                cache_key=cache_key,
                expires_at=expires_at,
                ttl_seconds=ttl_seconds,
                auto_renew=request.auto_renew
            )
        else:
            logger.error(f"API: Failed to cache keychain entry: {keychain_name}")
            raise HTTPException(
                status_code=500,
                detail="Failed to cache keychain entry"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API: Failed to cache keychain entry {keychain_name}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cache keychain entry: {str(e)}"
        )


@router.delete("/{catalog_id}/{keychain_name}", response_model=KeychainDeleteResponse)
async def delete_keychain_entry(
    catalog_id: int = Path(..., description="Catalog ID"),
    keychain_name: str = Path(..., description="Keychain entry name"),
    execution_id: Optional[int] = Query(None, description="Execution ID for local/shared scope"),
    scope_type: str = Query("global", description="Scope type")
) -> KeychainDeleteResponse:
    """
    Delete a keychain entry.
    
    Removes the entry from the keychain table.
    Useful for manually invalidating tokens or cleaning up cache.
    
    Returns success even if the key doesn't exist (idempotent).
    """
    try:
        # Delete from keychain using service layer
        deleted = await KeychainService.delete_keychain_entry(
            keychain_name=keychain_name,
            catalog_id=catalog_id,
            execution_id=execution_id,
            scope_type=scope_type
        )
        
        if deleted:
            logger.info(f"API: Deleted keychain entry: {keychain_name} (catalog: {catalog_id})")
            return KeychainDeleteResponse(
                status="success",
                message="Keychain entry deleted successfully",
                keychain_name=keychain_name,
                catalog_id=catalog_id
            )
        else:
            logger.warning(f"API: Failed to delete keychain entry: {keychain_name}")
            return KeychainDeleteResponse(
                status="error",
                message="Failed to delete keychain entry",
                keychain_name=keychain_name,
                catalog_id=catalog_id
            )
        
    except Exception as e:
        logger.error(f"API: Failed to delete keychain entry {keychain_name}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete keychain entry: {str(e)}"
        )


@router.get("/catalog/{catalog_id}", response_model=KeychainListResponse)
async def list_catalog_keychain_entries(
    catalog_id: int = Path(..., description="Catalog ID")
) -> KeychainListResponse:
    """
    List all keychain entries for a specific catalog.
    
    Returns summary information for all keychain entries associated
    with the given catalog_id, including expiration and access stats.
    """
    try:
        entries = await KeychainService.get_catalog_keychain_entries(catalog_id)
        
        logger.info(f"API: Retrieved {len(entries)} keychain entries for catalog {catalog_id}")
        
        return KeychainListResponse(
            status="success",
            catalog_id=catalog_id,
            entries=entries,
            count=len(entries)
        )
        
    except Exception as e:
        logger.error(f"API: Failed to list keychain entries for catalog {catalog_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list keychain entries: {str(e)}"
        )
