from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
import json
from noetl.logger import setup_logger

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
            from noetl.common import get_snowflake_id
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

        from noetl.common import get_db_connection
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
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
                row = cursor.fetchone()
                conn.commit()
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
    try:
        body = await request.json()
        name = (body.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        from noetl.common import get_db_connection
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE runtime
                    SET status = 'offline', updated_at = now()
                    WHERE component_type = 'worker_pool' AND name = %s
                    """,
                    (name,)
                )
                conn.commit()
        return {"status": "ok", "name": name}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error deregistering worker pool: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/worker/pool/register", response_class=JSONResponse)
async def register_worker_pool(request: Request):
    body = await request.json()
    logger.info(f"register_worker_pool: {body}")
    return JSONResponse(content={"status": "registered", "payload": body})


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


@router.delete("/worker/pool/deregister", response_class=JSONResponse)
async def deregister_worker_pool(request: Request):
    return JSONResponse(content={"status": "deregistered"})


@router.delete("/broker/deregister", response_class=JSONResponse)
async def deregister_broker(request: Request):
    return JSONResponse(content={"status": "deregistered"})
