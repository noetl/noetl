from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
import json
from noetl.logger import setup_logger
from noetl.common import get_async_db_connection, get_snowflake_id
from noetl.broker import execute_playbook_via_broker
from noetl.api.catalog import get_playbook_entry_from_catalog

logger = setup_logger(__name__, include_location=True)
router = APIRouter()


@router.post("/worker/pool/register", response_class=JSONResponse)
async def register_worker_pool(request: Request):
    """
    Register or update a worker pool in the runtime registry.
    Body:
      { name, runtime, base_url, status, capacity?, labels?, pid?, hostname?, meta? }
    """
    try:
        body = await request.json()
        name = (body.get("name") or "").strip()
        runtime = (body.get("runtime") or "").strip().lower()
        base_url = (body.get("base_url") or "").strip()
        status = (body.get("status") or "ready").strip().lower()
        capacity = body.get("capacity")
        labels = body.get("labels")
        pid = body.get("pid")
        hostname = body.get("hostname")
        meta = body.get("meta") or {}
        if not name or not runtime or not base_url:
            raise HTTPException(status_code=400, detail="name, runtime, and base_url are required")

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
                    INSERT INTO runtime (runtime_id, name, component_type, base_url, status, labels, capacity, runtime, last_heartbeat, created_at, updated_at)
                    VALUES (%s, %s, 'worker_pool', %s, %s, %s::jsonb, %s, %s::jsonb, now(), now(), now())
                    ON CONFLICT (component_type, name)
                    DO UPDATE SET
                        base_url = EXCLUDED.base_url,
                        status = EXCLUDED.status,
                        labels = EXCLUDED.labels,
                        capacity = EXCLUDED.capacity,
                        runtime = EXCLUDED.runtime,
                        last_heartbeat = now(),
                        updated_at = now()
                    RETURNING runtime_id
                    """,
                    (rid, name, base_url, status, labels_json, capacity, runtime_json)
                )
                row = await cursor.fetchone()
                try:
                    await conn.commit()
                except Exception:
                    pass
        return {"status": "ok", "name": name, "runtime": runtime, "runtime_id": row[0] if row else rid}
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
        component_type = (body.get("component_type") or "server_api").strip()
        runtime = (body.get("runtime") or "").strip().lower()
        base_url = (body.get("base_url") or "").strip()
        status = (body.get("status") or "ready").strip().lower()
        capacity = body.get("capacity")
        labels = body.get("labels")
        pid = body.get("pid")
        hostname = body.get("hostname")
        meta = body.get("meta") or {}
        
        if not name or not component_type or not base_url:
            raise HTTPException(status_code=400, detail="name, component_type, and base_url are required")

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
                    INSERT INTO runtime (runtime_id, name, component_type, base_url, status, labels, capacity, runtime, last_heartbeat, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, now(), now(), now())
                    ON CONFLICT (component_type, name)
                    DO UPDATE SET
                        base_url = EXCLUDED.base_url,
                        status = EXCLUDED.status,
                        labels = EXCLUDED.labels,
                        capacity = EXCLUDED.capacity,
                        runtime = EXCLUDED.runtime,
                        last_heartbeat = now(),
                        updated_at = now()
                    RETURNING runtime_id
                    """,
                    (rid, name, component_type, base_url, status, labels_json, capacity, runtime_json)
                )
                row = await cursor.fetchone()
                try:
                    await conn.commit()
                except Exception:
                    pass
        return {"status": "ok", "name": name, "component_type": component_type, "runtime_id": row[0] if row else rid}
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
    body = await request.json()
    #logger.info(f"heartbeat_worker_pool: {body}")
    return JSONResponse(content={"status": "ok"})


@router.get("/worker/pools", response_class=JSONResponse)
async def list_worker_pools(request: Request, runtime: Optional[str] = None, status: Optional[str] = None):
    return JSONResponse(content={"items": [], "runtime": runtime, "status": status})


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


@router.post("/executions/run", response_class=JSONResponse)
async def execute_playbook(request: Request):
    """
    Execute a playbook via the broker system.
    Body:
      { playbook_id: str, parameters?: dict, merge?: bool }
    """
    try:
        body = await request.json()
        playbook_id = body.get("playbook_id")
        parameters = body.get("parameters", {})
        merge = body.get("merge", False)

        if not playbook_id:
            raise HTTPException(
                status_code=400,
                detail="playbook_id is required."
            )

        logger.debug(f"EXECUTE_PLAYBOOK: Received request to execute playbook_id={playbook_id} with parameters={parameters}")

        # Fetch playbook entry from catalog
        entry = await get_playbook_entry_from_catalog(playbook_id)
        playbook_content = entry.get("content", "")

        # Execute playbook via broker
        result = execute_playbook_via_broker(
            playbook_content=playbook_content,
            playbook_path=playbook_id,
            playbook_version=entry.get("resource_version", "latest"),
            input_payload=parameters,
            sync_to_postgres=True,
            merge=merge
        )

        # Persist workload record for this execution (server-side tracking)
        try:
            exec_id = result.get("execution_id")
            if exec_id:
                from noetl.common import get_async_db_connection
                async with get_async_db_connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """
                            INSERT INTO workload (execution_id, data)
                            VALUES (%s, %s)
                            ON CONFLICT (execution_id) DO UPDATE SET data = EXCLUDED.data
                            """,
                            (exec_id, json.dumps(parameters or {}))
                        )
                        try:
                            await conn.commit()
                        except Exception:
                            pass
        except Exception as _we:
            logger.warning(f"Failed to upsert workload for execution: { _we }")

        execution = {
            "id": result.get("execution_id", ""),
            "playbook_id": playbook_id,
            "playbook_name": playbook_id.split("/")[-1],
            "status": "running",
            "start_time": result.get("timestamp", ""),
            "progress": 0,
            "result": result
        }

        logger.debug(f"EXECUTE_PLAYBOOK: Returning execution={execution}")
        return execution

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing playbook: {e}")
        raise HTTPException(status_code=500, detail=str(e))
