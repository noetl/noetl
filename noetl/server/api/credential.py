from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from psycopg.types.json import Json
from noetl.core.common import get_async_db_connection
from noetl.core.logger import setup_logger

router = APIRouter()
logger = setup_logger(__name__, include_location=True)


@router.post("/credentials", response_class=JSONResponse)
async def create_or_update_credential(request: Request):
    """Create or update a credential record.
    Body JSON fields:
      - name: required unique name
      - type: string (e.g., httpBearerAuth, serviceAccount), optional but recommended
      - data: required JSON object containing secret material (will be encrypted)
      - meta: optional arbitrary JSON metadata
      - tags: optional list of strings or comma-separated string
      - description: optional string
    """
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        name = (body.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="'name' is required")
        ctype = (body.get("type") or "").strip() or "generic"
        data = body.get("data")
        if data is None:
            raise HTTPException(status_code=400, detail="'data' is required")
        meta = body.get("meta")
        description = body.get("description")
        tags = body.get("tags")
        # Normalize tags
        if isinstance(tags, str):
            tag_list = [t.strip() for t in tags.split(',') if t and t.strip()]
        elif isinstance(tags, list):
            tag_list = [str(t) for t in tags]
        elif tags is None:
            tag_list = None
        else:
            tag_list = [str(tags)]

        # Encrypt data payload
        from noetl.secret import encrypt_json
        enc = encrypt_json(data)

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
                        name,
                        ctype,
                        enc,
                        Json(meta) if meta is not None else None,
                        tag_list,
                        description,
                    ),
                )
                row = await cursor.fetchone()
                try:
                    await conn.commit()
                except Exception:
                    pass
        result = {
            "id": row[0],
            "name": row[1],
            "type": row[2],
            "meta": row[3],
            "tags": row[4],
            "description": row[5],
            "created_at": row[6],
            "updated_at": row[7],
        }
        return JSONResponse(content=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error creating/updating credential: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/credentials", response_class=JSONResponse)
async def list_credentials(ctype: Optional[str] = None, q: Optional[str] = None):
    """List credentials with optional filter by type and free-text query on name/description."""
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
                    items.append({
                        "id": r[0],
                        "name": r[1],
                        "type": r[2],
                        "meta": r[3],
                        "tags": r[4],
                        "description": r[5],
                        "created_at": r[6],
                        "updated_at": r[7],
                    })
        return JSONResponse(content={"items": items, "filter": {"type": ctype, "q": q}})
    except Exception as e:
        logger.exception(f"Error listing credentials: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/credentials/{identifier}", response_class=JSONResponse)
async def get_credential(identifier: str, include_data: bool = False):
    """Get a credential by numeric id or by name. Optionally include decrypted data."""
    try:
        by_id = identifier.isdigit()
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cursor:
                if by_id:
                    await cursor.execute(
                        "SELECT id, name, type, data_encrypted, meta, tags, description, created_at, updated_at FROM credential WHERE id = %s",
                        (int(identifier),)
                    )
                else:
                    await cursor.execute(
                        "SELECT id, name, type, data_encrypted, meta, tags, description, created_at, updated_at FROM credential WHERE name = %s",
                        (identifier,)
                    )
                row = await cursor.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Credential not found")
                result = {
                    "id": row[0],
                    "name": row[1],
                    "type": row[2],
                    "meta": row[4],
                    "tags": row[5],
                    "description": row[6],
                    "created_at": row[7],
                    "updated_at": row[8]
                }
                if include_data:
                    try:
                        from noetl.secret import decrypt_json
                        result["data"] = decrypt_json(row[3])
                    except Exception as dec_err:
                        raise HTTPException(status_code=500, detail=f"Decryption failed: {dec_err}")
                return JSONResponse(content=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting credential: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/gcp/token", response_class=JSONResponse)
async def get_gcp_token(request: Request):
    """Obtain a GCP access token using service account credentials or ADC.
    Body JSON fields:
      - scopes: string or list of strings (default: https://www.googleapis.com/auth/cloud-platform)
      - credentials_path: optional path to a service account JSON file
      - use_metadata: optional bool; if true, try GCE metadata server first (not default)
      - service_account_secret: optional GCP Secret Manager resource path to JSON key (projects/...)
      - credentials_info: optional JSON object/string with service account info
      - store_as: optional name to persist issued token as credential
      - store_type/store_meta/store_description/store_tags: optional fields for persistence
    """
    import os as _os
    if str(_os.getenv("NOETL_ENABLE_GCP_TOKEN_API", "true")).lower() not in ["1","true","yes","y","on"]:
        raise HTTPException(status_code=404, detail="Not Found")
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}
        scopes = body.get("scopes")
        credentials_path = body.get("credentials_path")
        use_metadata = body.get("use_metadata", False)
        service_account_secret = body.get("service_account_secret")
        credentials_info = body.get("credentials_info")

        try:
            if credentials_info is None:
                cred_ref = body.get("credential") or body.get("credential_name") or body.get("credential_id")
                if cred_ref is not None:
                    async with get_async_db_connection(optional=True) as _conn:
                        if _conn is not None:
                            async with _conn.cursor() as _cur:
                                if isinstance(cred_ref, (int,)) or (isinstance(cred_ref, str) and cred_ref.isdigit()):
                                    await _cur.execute("SELECT data_encrypted FROM credential WHERE id = %s", (int(cred_ref),))
                                else:
                                    await _cur.execute("SELECT data_encrypted FROM credential WHERE name = %s", (str(cred_ref),))
                                _row = await _cur.fetchone()
                            if _row:
                                from noetl.secret import decrypt_json
                                try:
                                    credentials_info = decrypt_json(_row[0])
                                except Exception as _dec_err:
                                    logger.warning(f"/gcp/token: Failed to decrypt credential '{cred_ref}': {_dec_err}")
                        else:
                            logger.warning("/gcp/token: Database not available to resolve stored credential")
        except Exception as _cred_err:
            logger.warning(f"/gcp/token: Error resolving stored credential: {_cred_err}")

        import asyncio
        from noetl.secret import obtain_gcp_token
        async def _issue_token():
            return await asyncio.to_thread(
                obtain_gcp_token,
                scopes,
                credentials_path,
                use_metadata,
                service_account_secret,
                credentials_info
            )
        result = await _issue_token()

        try:
            store_as = body.get("store_as")
            if store_as and isinstance(store_as, str) and store_as.strip():
                name = store_as.strip()
                store_type = (body.get("store_type") or "httpBearerAuth").strip()
                store_meta = body.get("store_meta")
                store_description = body.get("store_description")
                store_tags = body.get("store_tags")
                tags_norm = None
                if isinstance(store_tags, str):
                    parts = [p.strip() for p in store_tags.split(',') if p.strip()]
                    tags_norm = parts if parts else None
                elif isinstance(store_tags, list):
                    tags_norm = [str(x) for x in store_tags]
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
                            (name, store_type, enc, Json(store_meta) if store_meta is not None else None, tags_norm, store_description)
                        )
                        await conn2.commit()
        except Exception as persist_err:
            logger.warning(f"/gcp/token: Failed to persist token: {persist_err}")

        return JSONResponse(content=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error obtaining GCP token: {e}")
        raise HTTPException(status_code=500, detail=str(e))
