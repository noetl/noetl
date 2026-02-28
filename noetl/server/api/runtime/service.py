"""
NoETL Runtime Service - Business logic for runtime component management.

Handles:
- Component registration and deregistration
- Heartbeat processing
- Component listing and querying
- Auto-recreation of missing components
"""

import json
from typing import Optional, Dict, Any, Tuple
from fastapi import HTTPException
from psycopg.rows import dict_row
from noetl.core.logger import setup_logger
from noetl.core.config import get_worker_settings
from noetl.core.common import get_async_db_connection, get_snowflake_id
from noetl.core.config import get_settings
from .schema import (
    RuntimeRegistrationRequest,
    RuntimeRegistrationResponse,
    RuntimeDeregistrationRequest,
    RuntimeHeartbeatRequest,
    RuntimeHeartbeatResponse,
    RuntimeComponentInfo,
    RuntimeListResponse
)

logger = setup_logger(__name__, include_location=True)


class RuntimeService:
    """
    Service for managing runtime component lifecycle.
    
    Provides:
    - Registration and deregistration of components
    - Heartbeat handling with auto-recreation
    - Component querying and listing
    """
    
    @staticmethod
    async def register_component(request: RuntimeRegistrationRequest) -> RuntimeRegistrationResponse:
        """
        Register or update a runtime component.
        
        Args:
            request: Registration request with component details
            
        Returns:
            RuntimeRegistrationResponse with runtime_id
            
        Raises:
            HTTPException: If registration fails or validation errors
        """
        # Validate URI requirements
        if request.kind in ["server_api", "broker"] and not request.uri:
            raise HTTPException(
                status_code=400,
                detail=f"uri is required for {request.kind} components"
            )
        
        # Generate runtime ID
        import datetime as _dt
        try:
            rid = get_snowflake_id()
        except Exception:
            rid = int(_dt.datetime.now().timestamp() * 1000)
        
        # Prepare runtime metadata
        payload_runtime = {
            "type": request.runtime,
            "pid": request.pid,
            "hostname": request.hostname,
            **({} if not isinstance(request.meta, dict) else request.meta),
        }
        
        # Convert to JSON for storage
        labels_json = json.dumps(request.labels) if request.labels is not None else None
        runtime_json = json.dumps(payload_runtime)
        
        # Upsert to database
        row = None
        db_error = None
        
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO noetl.runtime (runtime_id, name, kind, uri, status, labels, capacity, runtime, heartbeat, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, now(), now(), now())
                        ON CONFLICT (kind, name)
                        DO UPDATE SET
                            uri = EXCLUDED.uri,
                            status = EXCLUDED.status,
                            labels = EXCLUDED.labels,
                            capacity = EXCLUDED.capacity,
                            runtime = EXCLUDED.runtime,
                            heartbeat = now(),
                            updated_at = now()
                        RETURNING runtime_id
                        """,
                        (rid, request.name, request.kind, request.uri, request.status, 
                         labels_json, request.capacity, runtime_json)
                    )
                    row = await cursor.fetchone()
                    try:
                        await conn.commit()
                    except Exception as e:
                        logger.warning(f"Commit warning (may auto-commit): {e}")
        except Exception as e:
            logger.error(f"Database error during component registration: {e}")
            db_error = e
        
        # Check for errors after context manager exits
        if db_error:
            raise HTTPException(
                status_code=500,
                detail=f"Database error: {str(db_error)}"
            )
        
        # dict_row returns a dictionary, access by column name
        runtime_id = str(row['runtime_id']) if row else str(rid)
        
        return RuntimeRegistrationResponse(
            status="ok",
            name=request.name,
            runtime_id=runtime_id,
            kind=request.kind,
            runtime=request.runtime
        )
    
    @staticmethod
    async def deregister_component(request: RuntimeDeregistrationRequest) -> RuntimeRegistrationResponse:
        """
        Deregister a runtime component (marks as offline).
        
        Args:
            request: Deregistration request with component name and kind
            
        Returns:
            RuntimeRegistrationResponse with status
            
        Raises:
            HTTPException: If deregistration fails
        """
        db_error = None
        
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cursor:
                    await cursor.execute(
                        """
                        UPDATE noetl.runtime
                        SET status = 'offline', updated_at = now()
                        WHERE kind = %s AND name = %s
                        """,
                        (request.kind, request.name)
                    )
                    try:
                        await conn.commit()
                    except Exception as e:
                        logger.warning(f"Commit warning: {e}")
        except Exception as e:
            logger.error(f"Database error during deregistration: {e}")
            db_error = e
        
        if db_error:
            raise HTTPException(
                status_code=500,
                detail=f"Database error: {str(db_error)}"
            )
        
        return RuntimeRegistrationResponse(
            status="ok",
            name=request.name,
            kind=request.kind
        )
    
    @staticmethod
    async def process_heartbeat(request: RuntimeHeartbeatRequest) -> RuntimeHeartbeatResponse:
        """
        Process heartbeat from a runtime component.
        
        Supports auto-recreation of missing components if configured.
        
        Args:
            request: Heartbeat request with component name
            
        Returns:
            RuntimeHeartbeatResponse with status
            
        Raises:
            HTTPException: If component not found and auto-recreation disabled
        """
        worker_settings = get_worker_settings()

        # Get name from request or configuration
        name = request.name or worker_settings.resolved_pool_name
        
        if not name:
            # For backward compatibility, return ok without DB update
            return RuntimeHeartbeatResponse(
                status="ok",
                name=None
            )
        
        # Try to update heartbeat
        updated = False
        runtime_id: Optional[str] = None
        db_error = None
        
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    try:
                        await cur.execute(
                            """
                            UPDATE noetl.runtime
                            SET heartbeat = now(), status = 'ready', updated_at = now()
                            WHERE kind = 'worker_pool' AND name = %s
                            RETURNING runtime_id
                            """,
                            (name,)
                        )
                        row = await cur.fetchone()
                        if row:
                            updated = True
                            runtime_id = str(row[0])
                    except Exception as e:
                        logger.warning(f"Heartbeat update failed for worker pool {name}: {e}")
                    try:
                        await conn.commit()
                    except Exception as e:
                        logger.warning(f"Commit warning: {e}")
        except Exception as e:
            logger.debug(f"Heartbeat DB connection issue for {name}: {e}")
            db_error = e
        
        # If not updated, check auto-recreation settings
        if not updated:
            settings = get_settings()
            auto_recreate_runtime = getattr(settings, 'auto_recreate_runtime', False)
            heartbeat_retry_after = getattr(settings, 'heartbeat_retry_after', 3)
            
            if auto_recreate_runtime and request.registration:
                # Try to recreate from registration data
                try:
                    recreated = await RuntimeService._upsert_worker_pool(
                        request.registration,
                        require_full_payload=False
                    )
                    if recreated:
                        logger.info(f"Worker pool {recreated['name']} auto-recreated from heartbeat")
                        return RuntimeHeartbeatResponse(
                            status="recreated",
                            name=recreated["name"],
                            runtime=recreated["runtime"],
                            runtime_id=recreated["runtime_id"]
                        )
                except HTTPException as exc:
                    if exc.status_code != 400:
                        raise
                    logger.debug(f"Unable to auto-recreate worker pool {name}; insufficient data")
            
            # Component not found and can't recreate
            headers = {"Retry-After": str(heartbeat_retry_after)}
            raise HTTPException(
                status_code=404,
                detail={"status": "unknown", "name": name},
                headers=headers
            )
        
        return RuntimeHeartbeatResponse(
            status="ok",
            name=name,
            runtime_id=runtime_id
        )
    
    @staticmethod
    async def _upsert_worker_pool(
        payload: Dict[str, Any], 
        *, 
        require_full_payload: bool
    ) -> Optional[Dict[str, Any]]:
        """
        Internal helper to insert or update a worker pool.
        
        Args:
            payload: Registration payload
            require_full_payload: If True, raise exception on missing required fields
            
        Returns:
            Dict with runtime_id, name, runtime, status or None
        """
        body = payload or {}
        name = (body.get("name") or "").strip()
        runtime = (body.get("runtime") or "").strip().lower()
        uri = (body.get("uri") or body.get("endpoint") or body.get("base_url") or "").strip() or None
        status = (body.get("status") or "ready").strip().lower()
        capacity = body.get("capacity")
        labels = body.get("labels")
        pid = body.get("pid")
        hostname = body.get("hostname")
        meta = body.get("meta") or {}

        # Workers don't need URIs, only name and runtime are required
        if not name or not runtime:
            if require_full_payload:
                raise HTTPException(status_code=400, detail="name and runtime are required")
            return None

        import datetime as _dt
        try:
            rid = get_snowflake_id()
        except Exception:
            rid = int(_dt.datetime.now().timestamp() * 1000)

        payload_runtime = {
            "type": runtime,
            "pid": pid,
            "hostname": hostname,
            **({} if not isinstance(meta, dict) else meta),
        }

        labels_json = json.dumps(labels) if labels is not None else None
        runtime_json = json.dumps(payload_runtime)

        row = None
        db_error = None
        
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO noetl.runtime (runtime_id, name, kind, uri, status, labels, capacity, runtime, heartbeat, created_at, updated_at)
                        VALUES (%s, %s, 'worker_pool', %s, %s, %s::jsonb, %s, %s::jsonb, now(), now(), now())
                        ON CONFLICT (kind, name)
                        DO UPDATE SET
                            uri = EXCLUDED.uri,
                            status = EXCLUDED.status,
                            labels = EXCLUDED.labels,
                            capacity = EXCLUDED.capacity,
                            runtime = EXCLUDED.runtime,
                            heartbeat = now(),
                            updated_at = now()
                        RETURNING runtime_id
                        """,
                        (rid, name, uri, status, labels_json, capacity, runtime_json)
                    )
                    row = await cursor.fetchone()
                    try:
                        await conn.commit()
                    except Exception as e:
                        logger.warning(f"Commit warning: {e}")
        except Exception as e:
            logger.error(f"Database error during worker pool upsert: {e}")
            db_error = e
        
        if db_error:
            raise HTTPException(
                status_code=500,
                detail=f"Database error: {str(db_error)}"
            )

        runtime_id = str(row[0]) if row else str(rid)
        return {
            "runtime_id": runtime_id, 
            "name": name, 
            "runtime": runtime, 
            "status": status
        }
    
    @staticmethod
    async def list_components(
        kind: str = "worker_pool",
        runtime: Optional[str] = None,
        status: Optional[str] = None
    ) -> RuntimeListResponse:
        """
        List runtime components with optional filters.
        
        Args:
            kind: Component type to filter by
            runtime: Optional runtime type filter
            status: Optional status filter
            
        Returns:
            RuntimeListResponse with list of components
        """
        items = []
        error_msg = None
        
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cursor:
                    # Build query with optional filters
                    where_clauses = ["kind = %s"]
                    params = [kind]
                    
                    if runtime:
                        where_clauses.append("(runtime::json->>'type' = %s)")
                        params.append(runtime.lower())
                    
                    if status:
                        where_clauses.append("status = %s")
                        params.append(status.lower())
                    
                    query = f"""
                        SELECT name, runtime, status, capacity, labels, heartbeat, created_at, updated_at
                        FROM noetl.runtime 
                        WHERE {' AND '.join(where_clauses)}
                        ORDER BY name
                    """
                    
                    await cursor.execute(query, params)
                    rows = await cursor.fetchall()
                    
                    def _to_iso(v):
                        if v is None:
                            return None
                        if isinstance(v, str):
                            return v
                        return v.isoformat()

                    for row in rows:
                        items.append(RuntimeComponentInfo(
                            name=row["name"],
                            runtime=row["runtime"],
                            status=row["status"],
                            capacity=row["capacity"],
                            labels=row["labels"],
                            heartbeat=_to_iso(row["heartbeat"]),
                            created_at=_to_iso(row["created_at"]),
                            updated_at=_to_iso(row["updated_at"]),
                        ))
        except Exception as e:
            logger.exception(f"Error listing components: {e}")
            error_msg = str(e)
        
        return RuntimeListResponse(
            items=items,
            count=len(items),
            runtime=runtime,
            status=status,
            error=error_msg
        )
