"""
NoETL Credential API Service - Business logic for credential operations.

Handles:
- Credential encryption/decryption
- Database persistence
- GCP token generation
"""

from typing import Optional, Dict, Any, List
from fastapi import HTTPException
from psycopg.types.json import Json
from noetl.core.common import get_async_db_connection
from noetl.core.logger import setup_logger
from .schema import (
    CredentialCreateRequest,
    CredentialResponse,
    CredentialListResponse,
    GCPTokenRequest,
    GCPTokenResponse
)

logger = setup_logger(__name__, include_location=True)


class CredentialService:
    """Service class for credential operations."""
    
    @staticmethod
    async def create_or_update_credential(request: CredentialCreateRequest) -> CredentialResponse:
        """
        Create or update a credential with encryption.
        
        Args:
            request: Credential creation/update request
            
        Returns:
            CredentialResponse with created/updated credential info
            
        Raises:
            HTTPException: If operation fails
        """
        # Validate required fields
        if not request.name:
            raise HTTPException(status_code=400, detail="'name' is required")
        
        if request.data is None:
            raise HTTPException(status_code=400, detail="'data' is required")
        
        # Encrypt data payload
        from noetl.secret import encrypt_json
        try:
            enc = encrypt_json(request.data)
        except Exception as e:
            logger.error(f"Failed to encrypt credential data: {e}")
            raise HTTPException(status_code=500, detail=f"Encryption failed: {str(e)}")
        
        # Persist to database
        db_error = None
        row = None
        
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO credential(name, type, data_encrypted, meta, tags, description)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT(name) DO UPDATE SET
                          type=EXCLUDED.type,
                          data_encrypted=EXCLUDED.data_encrypted,
                          meta=EXCLUDED.meta,
                          tags=EXCLUDED.tags,
                          description=EXCLUDED.description,
                          updated_at=now()
                        RETURNING id, name, type, meta, tags, description, created_at, updated_at
                        """,
                        (
                            request.name,
                            request.type,
                            enc,
                            Json(request.meta) if request.meta is not None else None,
                            request.tags,
                            request.description,
                        ),
                    )
                    row = await cursor.fetchone()
                    try:
                        await conn.commit()
                    except Exception as e:
                        logger.warning(f"Commit warning (may auto-commit): {e}")
        except Exception as e:
            logger.error(f"Database error during credential creation: {e}")
            db_error = e
        
        # Check for errors after context manager exits
        if db_error:
            raise HTTPException(
                status_code=500,
                detail=f"Database error: {str(db_error)}"
            )
        
        if not row:
            raise HTTPException(
                status_code=500,
                detail="Failed to create/update credential"
            )
        
        return CredentialResponse(
            id=str(row[0]),
            name=row[1],
            type=row[2],
            meta=row[3],
            tags=row[4],
            description=row[5],
            created_at=row[6],
            updated_at=row[7]
        )
    
    @staticmethod
    async def list_credentials(
        ctype: Optional[str] = None,
        q: Optional[str] = None
    ) -> CredentialListResponse:
        """
        List credentials with optional filtering.
        
        Args:
            ctype: Filter by credential type
            q: Free-text search on name/description
            
        Returns:
            CredentialListResponse with list of credentials
            
        Raises:
            HTTPException: If operation fails
        """
        try:
            conditions = []
            params = []
            
            if ctype:
                conditions.append("type = %s")
                params.append(ctype)
            
            if q:
                conditions.append("(name ILIKE %s OR description ILIKE %s)")
                params.extend([f"%{q}%", f"%{q}%"])
            
            where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
            sql = f"""
                SELECT id, name, type, meta, tags, description, created_at, updated_at
                FROM credential
                {where_clause}
                ORDER BY name ASC
            """
            
            items = []
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(sql, params)
                    rows = await cursor.fetchall() or []
                    
                    for r in rows:
                        items.append(CredentialResponse(
                            id=str(r[0]),
                            name=r[1],
                            type=r[2],
                            meta=r[3],
                            tags=r[4],
                            description=r[5],
                            created_at=r[6],
                            updated_at=r[7]
                        ))
            
            return CredentialListResponse(
                items=items,
                filter={"type": ctype, "q": q}
            )
            
        except Exception as e:
            logger.exception(f"Error listing credentials: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def get_credential(
        identifier: str,
        include_data: bool = False
    ) -> CredentialResponse:
        """
        Get a credential by ID or name.
        
        Args:
            identifier: Credential ID (numeric) or name
            include_data: Whether to include decrypted data
            
        Returns:
            CredentialResponse with credential info
            
        Raises:
            HTTPException: If credential not found or operation fails
        """
        try:
            by_id = identifier.isdigit()
            
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    if by_id:
                        await cursor.execute(
                            """
                            SELECT id, name, type, data_encrypted, meta, tags, description, created_at, updated_at
                            FROM credential
                            WHERE id = %s
                            """,
                            (int(identifier),)
                        )
                    else:
                        await cursor.execute(
                            """
                            SELECT id, name, type, data_encrypted, meta, tags, description, created_at, updated_at
                            FROM credential
                            WHERE name = %s
                            """,
                            (identifier,)
                        )
                    
                    row = await cursor.fetchone()
                    
                    if not row:
                        raise HTTPException(
                            status_code=404,
                            detail="Credential not found"
                        )
                    
                    response = CredentialResponse(
                        id=str(row[0]),
                        name=row[1],
                        type=row[2],
                        meta=row[4],
                        tags=row[5],
                        description=row[6],
                        created_at=row[7],
                        updated_at=row[8]
                    )
                    
                    if include_data:
                        try:
                            from noetl.secret import decrypt_json
                            response.data = decrypt_json(row[3])
                        except Exception as dec_err:
                            logger.error(f"Failed to decrypt credential: {dec_err}")
                            raise HTTPException(
                                status_code=500,
                                detail=f"Decryption failed: {str(dec_err)}"
                            )
                    
                    return response
                    
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Error getting credential: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @staticmethod
    async def get_gcp_token(request: GCPTokenRequest) -> GCPTokenResponse:
        """
        Obtain a GCP access token using various credential sources.
        
        Args:
            request: GCP token request with credential sources
            
        Returns:
            GCPTokenResponse with access token
            
        Raises:
            HTTPException: If token generation fails or API is disabled
        """
        import os as _os
        import asyncio
        
        # Check if API is enabled
        if str(_os.getenv("NOETL_ENABLE_GCP_TOKEN_API", "true")).lower() not in ["1", "true", "yes", "y", "on"]:
            raise HTTPException(status_code=404, detail="Not Found")
        
        credentials_info = request.credentials_info
        
        # Try to resolve stored credential if referenced
        try:
            if credentials_info is None:
                cred_ref = request.credential or request.credential_id
                if cred_ref is not None:
                    async with get_async_db_connection(optional=True) as _conn:
                        if _conn is not None:
                            async with _conn.cursor() as _cur:
                                if isinstance(cred_ref, int) or (isinstance(cred_ref, str) and cred_ref.isdigit()):
                                    await _cur.execute(
                                        "SELECT data_encrypted FROM credential WHERE id = %s",
                                        (int(cred_ref),)
                                    )
                                else:
                                    await _cur.execute(
                                        "SELECT data_encrypted FROM credential WHERE name = %s",
                                        (str(cred_ref),)
                                    )
                                _row = await _cur.fetchone()
                            
                            if _row:
                                from noetl.secret import decrypt_json
                                try:
                                    credentials_info = decrypt_json(_row[0])
                                except Exception as _dec_err:
                                    logger.warning(
                                        f"Failed to decrypt credential '{cred_ref}': {_dec_err}"
                                    )
                        else:
                            logger.warning("Database not available to resolve stored credential")
        except Exception as _cred_err:
            logger.warning(f"Error resolving stored credential: {_cred_err}")
        
        # Generate token
        try:
            from noetl.secret import obtain_gcp_token
            
            async def _issue_token():
                return await asyncio.to_thread(
                    obtain_gcp_token,
                    request.scopes,
                    request.credentials_path,
                    request.use_metadata,
                    request.service_account_secret,
                    credentials_info
                )
            
            result = await _issue_token()
            
            # Optionally store the token as a credential
            if request.store_as and isinstance(request.store_as, str) and request.store_as.strip():
                try:
                    name = request.store_as.strip()
                    store_type = (request.store_type or "httpBearerAuth").strip()
                    
                    # Normalize tags
                    tags_norm = None
                    if isinstance(request.store_tags, str):
                        parts = [p.strip() for p in request.store_tags.split(',') if p.strip()]
                        tags_norm = parts if parts else None
                    elif isinstance(request.store_tags, list):
                        tags_norm = [str(x) for x in request.store_tags]
                    
                    token_payload = {
                        "access_token": result.get("access_token"),
                        "token_expiry": result.get("token_expiry"),
                        "scopes": result.get("scopes"),
                    }
                    
                    from noetl.secret import encrypt_json
                    enc = encrypt_json(token_payload)
                    
                    async with get_async_db_connection() as conn2:
                        async with conn2.cursor() as cursor2:
                            await cursor2.execute(
                                """
                                INSERT INTO credential(name, type, data_encrypted, meta, tags, description)
                                VALUES (%s, %s, %s, %s, %s, %s)
                                ON CONFLICT(name) DO UPDATE SET
                                  type=EXCLUDED.type,
                                  data_encrypted=EXCLUDED.data_encrypted,
                                  meta=EXCLUDED.meta,
                                  tags=EXCLUDED.tags,
                                  description=EXCLUDED.description,
                                  updated_at=now()
                                """,
                                (
                                    name,
                                    store_type,
                                    enc,
                                    Json(request.store_meta) if request.store_meta is not None else None,
                                    tags_norm,
                                    request.store_description
                                )
                            )
                            await conn2.commit()
                except Exception as persist_err:
                    logger.warning(f"Failed to persist token: {persist_err}")
            
            return GCPTokenResponse(
                access_token=result.get("access_token", ""),
                token_expiry=result.get("token_expiry"),
                scopes=result.get("scopes")
            )
            
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Error obtaining GCP token: {e}")
            raise HTTPException(status_code=500, detail=str(e))
