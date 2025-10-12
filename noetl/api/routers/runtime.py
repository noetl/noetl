from typing import Optional, Dict, Any
import os
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
import json
from noetl.core.logger import setup_logger
from noetl.core.common import get_async_db_connection, get_snowflake_id
from noetl.core.config import get_settings
from noetl.api.routers.broker import execute_playbook_via_broker
from noetl.api.routers.catalog import get_playbook_entry_from_catalog

logger = setup_logger(__name__, include_location=True)
router = APIRouter()


async def _upsert_worker_pool(payload: Dict[str, Any], *, require_full_payload: bool) -> Optional[Dict[str, Any]]:
    """Insert or update a worker pool runtime row."""
    body = payload or {}
    name = (body.get("name") or "").strip()
    runtime = (body.get("runtime") or "").strip().lower()
    uri = (body.get("uri") or body.get("endpoint") or body.get("base_url") or "").strip() or None  # Support legacy names
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

    async with get_async_db_connection() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(
                """
                INSERT INTO runtime (runtime_id, name, kind, uri, status, labels, capacity, runtime, heartbeat, created_at, updated_at)
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
            except Exception:
                pass

    runtime_id = row[0] if row else rid
    return {"runtime_id": runtime_id, "name": name, "runtime": runtime, "status": status}


@router.post("/worker/pool/register", response_class=JSONResponse)
async def register_worker_pool(request: Request):
    """
    Register or update a worker pool in the runtime registry.
    Body:
      { name, runtime, base_url, status, capacity?, labels?, pid?, hostname?, meta? }
    """
    try:
        body = await request.json()
        result = await _upsert_worker_pool(body, require_full_payload=True)
        return {"status": "ok", "name": result["name"], "runtime": result["runtime"], "runtime_id": result["runtime_id"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error registering worker pool: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/worker/pool/deregister", response_class=JSONResponse)
async def deregister_worker_pool(request: Request):
    """
    Deregister a worker pool by name (marks as offline).
    Body: { name }
    """
    logger.info("Worker deregister endpoint called")
    try:
        body = await request.json()
        name = (body.get("name") or "").strip()
        logger.info(f"Deregistering worker pool: {name}")
        if not name:
            raise HTTPException(status_code=400, detail="name is required")

        logger.info(f"Opening database connection for worker deregistration")
        async with get_async_db_connection() as conn:
            logger.info(f"Database connection opened successfully")
            async with conn.cursor() as cursor:
                logger.info(f"Executing UPDATE query for worker: {name}")
                await cursor.execute(
                    """
                    UPDATE runtime
                    SET status = 'offline', updated_at = now()
                    WHERE component_type = 'worker_pool' AND name = %s
                    """,
                    (name,)
                )
                logger.info(f"Query executed, about to commit transaction")
                try:
                    await conn.commit()
                    logger.info(f"Worker {name} marked as offline in database")
                except Exception as e:
                    logger.error(f"Database commit failed: {e}")
                    raise

        logger.info(f"Worker deregistration completed for: {name}")
        return {"status": "ok", "name": name}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error deregistering worker pool: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Compatibility: some workers use POST instead of DELETE
@router.post("/worker/pool/deregister", response_class=JSONResponse)
async def deregister_worker_pool_post(request: Request):
    return await deregister_worker_pool(request)


@router.post("/runtime/register", response_class=JSONResponse)
async def register_runtime_component(request: Request):
    """
    Register a runtime component (server, worker_pool, broker, etc.) in the runtime registry.
    Body:
      { name, component_type, runtime?, base_url, status?, capacity?, labels?, pid?, hostname?, meta? }
    """
    try:
        body = await request.json()
        name = (body.get("name") or "").strip()
        kind = (body.get("kind") or body.get("component_type") or "server_api").strip()  # Support legacy name
        runtime = (body.get("runtime") or "").strip().lower()
        uri = (body.get("uri") or body.get("endpoint") or body.get("base_url") or "").strip() or None  # Support legacy names
        status = (body.get("status") or "ready").strip().lower()
        capacity = body.get("capacity")
        labels = body.get("labels")
        pid = body.get("pid")
        hostname = body.get("hostname")
        meta = body.get("meta") or {}
        
        # Only require URI for server_api and broker, not for worker_pool
        if not name or not kind:
            raise HTTPException(status_code=400, detail="name and kind are required")
        if kind in ["server_api", "broker"] and not uri:
            raise HTTPException(status_code=400, detail="uri is required for server_api and broker components")

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

        async with get_async_db_connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    f"""
                    INSERT INTO runtime (runtime_id, name, kind, uri, status, labels, capacity, runtime, heartbeat, created_at, updated_at)
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
                    (rid, name, kind, uri, status, labels_json, capacity, runtime_json)
                )
                row = await cursor.fetchone()
                try:
                    await conn.commit()
                except Exception:
                    pass
        return {"status": "ok", "name": name, "kind": kind, "runtime_id": row[0] if row else rid}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error registering runtime component: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/runtime/deregister", response_class=JSONResponse)
async def deregister_runtime_component(request: Request):
    """
    Deregister a runtime component by name and component_type (marks as offline).
    Body: { name, component_type }
    """
    try:
        body = await request.json()
        name = (body.get("name") or "").strip()
        component_type = (body.get("component_type") or "server_api").strip()
        if not name or not component_type:
            raise HTTPException(status_code=400, detail="name and component_type are required")
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE runtime
                    SET status = 'offline', updated_at = now()
                    WHERE component_type = %s AND name = %s
                    """,
                    (component_type, name)
                )
                try:
                    await conn.commit()
                except Exception:
                    pass
        return {"status": "ok", "name": name, "component_type": component_type}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error deregistering runtime component: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/worker/pool/heartbeat", response_class=JSONResponse)
async def heartbeat_worker_pool(request: Request):
    """Persist heartbeat for a worker pool.

    Body (minimal): { name: str }
    Optional extra fields are ignored. If the runtime row does not exist we
    return status=unknown so caller can decide to re-register.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    name = (body.get("name") or "").strip() or os.environ.get("NOETL_WORKER_POOL_NAME", "").strip()
    if not name:
        # For backward compatibility with older tests that didn't send a name,
        # just return ok without DB update. (Avoid raising 400 in that case.)
        return JSONResponse(content={"status": "ok", "name": None})

    updated = False
    runtime_id: Optional[int] = None
    try:
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                try:
                    await cur.execute(
                        """
                        UPDATE runtime
                        SET heartbeat = now(), status = 'ready', updated_at = now()
                        WHERE kind = 'worker_pool' AND name = %s
                        RETURNING runtime_id
                        """,
                        (name,)
                    )
                    row = await cur.fetchone()
                    if row:
                        updated = True
                        runtime_id = row[0]
                except Exception as e:
                    logger.warning(f"Heartbeat update failed for worker pool {name}: {e}")
                try:
                    await conn.commit()
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"Heartbeat DB connection issue for {name}: {e}")

    if not updated:
        settings = get_settings()
        auto_recreate_runtime = getattr(settings, 'auto_recreate_runtime', False)
        heartbeat_retry_after = getattr(settings, 'heartbeat_retry_after', 3)
        if auto_recreate_runtime:
            registration_payload = body.get("registration") if isinstance(body, dict) else None
            if registration_payload is None:
                registration_payload = body
            try:
                recreated = await _upsert_worker_pool(registration_payload or {}, require_full_payload=False)
            except HTTPException as exc:
                if exc.status_code == 400:
                    recreated = None
                else:
                    raise
            if recreated:
                logger.info(f"Worker pool {recreated['name']} auto-recreated from heartbeat")
                return JSONResponse(content={"status": "recreated", "name": recreated["name"], "runtime": recreated["runtime"], "runtime_id": recreated["runtime_id"]})
            else:
                logger.debug(f"Unable to auto-recreate worker pool {name}; insufficient registration data in heartbeat payload")
        else:
            heartbeat_retry_after = getattr(settings, 'heartbeat_retry_after', 3)
        headers = {"Retry-After": str(heartbeat_retry_after)}
        raise HTTPException(status_code=404, detail={"status": "unknown", "name": name}, headers=headers)

    return JSONResponse(content={"status": "ok", "name": name, "runtime_id": runtime_id})


@router.get("/worker/pools", response_class=JSONResponse)
async def list_worker_pools(request: Request, runtime: Optional[str] = None, status: Optional[str] = None):
    """List all registered worker pools from the runtime table."""
    try:
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cursor:
                # Build query with optional filters
                where_clauses = ["kind = 'worker_pool'"]
                params = []
                
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
                
                items = []
                for row in rows:
                    name, runtime_data, status, capacity, labels, heartbeat, created_at, updated_at = row
                    items.append({
                        "name": name,
                        "runtime": runtime_data,
                        "status": status,
                        "capacity": capacity,
                        "labels": labels,
                        "heartbeat": heartbeat.isoformat() if heartbeat else None,
                        "created_at": created_at.isoformat() if created_at else None,
                        "updated_at": updated_at.isoformat() if updated_at else None
                    })
                
                return JSONResponse(content={
                    "items": items, 
                    "runtime": runtime, 
                    "status": status,
                    "count": len(items)
                })
    except Exception as e:
        logger.exception(f"Error listing worker pools: {e}")
        return JSONResponse(content={"items": [], "runtime": runtime, "status": status, "error": str(e)})


@router.post("/broker/register", response_class=JSONResponse)
async def register_broker(request: Request):
    body = await request.json()
    logger.info(f"register_broker: {body}")
    return JSONResponse(content={"status": "registered", "payload": body})


@router.post("/broker/heartbeat", response_class=JSONResponse)
async def heartbeat_broker(request: Request):
    body = await request.json()
    # logger.info(f"heartbeat_broker: {body}")
    return JSONResponse(content={"status": "ok"})


@router.get("/brokers", response_class=JSONResponse)
async def list_brokers(request: Request, status: Optional[str] = None):
    return JSONResponse(content={"items": [], "status": status})


@router.delete("/broker/deregister", response_class=JSONResponse)
async def deregister_broker(request: Request):
    return JSONResponse(content={"status": "deregistered"})
