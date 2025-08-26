import json
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from noetl.common import get_db_connection
from noetl.logger import setup_logger


logger = setup_logger(__name__, include_location=True)
router = APIRouter()
router = APIRouter(tags=["Queue"])

@router.post("/queue/enqueue", response_class=JSONResponse)
async def enqueue_job(request: Request):
    """Enqueue a job into the noetl.queue table.
    Body: { execution_id, node_id, action, input_context?, priority?, max_attempts?, available_at? }
    """
    try:
        body = await request.json()
        execution_id = body.get("execution_id")
        node_id = body.get("node_id")
        action = body.get("action")
        input_context = body.get("input_context", {})
        priority = int(body.get("priority", 0))
        max_attempts = int(body.get("max_attempts", 5))
        available_at = body.get("available_at")

        if not execution_id or not node_id or not action:
            raise HTTPException(status_code=400, detail="execution_id, node_id and action are required")

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO noetl.queue (execution_id, node_id, action, input_context, priority, max_attempts, available_at)
                    VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)
                    RETURNING id
                    """,
                    (execution_id, node_id, action, json.dumps(input_context), priority, max_attempts, available_at)
                )
                row = cur.fetchone()
                conn.commit()
        return {"status": "ok", "id": row[0]}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error enqueueing job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/lease", response_class=JSONResponse)
async def lease_job(request: Request):
    """Atomically lease a queued job for a worker.
    Body: { worker_id, lease_seconds? }
    Returns queued job or {status: 'empty'} when nothing available.
    """
    try:
        body = await request.json()
        worker_id = body.get("worker_id")
        lease_seconds = int(body.get("lease_seconds", 60))
        if not worker_id:
            raise HTTPException(status_code=400, detail="worker_id is required")

        with get_db_connection() as conn:
            # return dict-like row for JSON friendliness
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    WITH cte AS (
                      SELECT id FROM noetl.queue
                      WHERE status='queued' AND available_at <= now()
                      ORDER BY priority DESC, id
                      FOR UPDATE SKIP LOCKED
                      LIMIT 1
                    )
                    UPDATE noetl.queue q
                    SET status='leased',
                        worker_id=%s,
                        lease_until=now() + (%s || ' seconds')::interval,
                        last_heartbeat=now(),
                        attempts = q.attempts + 1
                    FROM cte
                    WHERE q.id = cte.id
                    RETURNING q.*;
                    """,
                    (worker_id, str(lease_seconds))
                )
                row = cur.fetchone()
                conn.commit()

        if not row:
            return {"status": "empty"}

        # ensure JSON serializable
        if row.get("input_context") is None:
            row["input_context"] = {}
        return {"status": "ok", "job": row}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error leasing job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/{job_id}/complete", response_class=JSONResponse)
async def complete_job(job_id: int):
    """Mark a job completed."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE noetl.queue SET status='done', lease_until = NULL, updated_at = now() WHERE id = %s RETURNING id", (job_id,))
                row = cur.fetchone()
                conn.commit()
        if not row:
            raise HTTPException(status_code=404, detail="job not found")
        return {"status": "ok", "id": job_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error completing job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/{job_id}/fail", response_class=JSONResponse)
async def fail_job(job_id: int, request: Request):
    """Mark job failed; optionally reschedule if attempts < max_attempts.
    Body: { retry_delay_seconds? }
    """
    try:
        body = await request.json()
        retry_delay = int(body.get("retry_delay_seconds", 60))
        with get_db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT attempts, max_attempts FROM noetl.queue WHERE id = %s", (job_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="job not found")
                attempts = row.get("attempts", 0)
                max_attempts = row.get("max_attempts", 5)

                if attempts >= max_attempts:
                    cur.execute("UPDATE noetl.queue SET status='dead', updated_at = now() WHERE id = %s RETURNING id", (job_id,))
                else:
                    cur.execute("UPDATE noetl.queue SET status='queued', available_at = now() + (%s || ' seconds')::interval, updated_at = now() WHERE id = %s RETURNING id", (str(retry_delay), job_id))
                updated = cur.fetchone()
                conn.commit()
        return {"status": "ok", "id": job_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error failing job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/{job_id}/heartbeat", response_class=JSONResponse)
async def heartbeat_job(job_id: int, request: Request):
    """Update heartbeat and optionally extend lease_until.
    Body: { worker_id?, extend_seconds? }
    """
    try:
        body = await request.json()
        worker_id = body.get("worker_id")
        extend = body.get("extend_seconds")
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                if extend:
                    cur.execute("UPDATE noetl.queue SET last_heartbeat = now(), lease_until = now() + (%s || ' seconds')::interval WHERE id = %s RETURNING id", (str(int(extend)), job_id))
                else:
                    cur.execute("UPDATE noetl.queue SET last_heartbeat = now() WHERE id = %s RETURNING id", (job_id,))
                row = cur.fetchone()
                conn.commit()
        if not row:
            raise HTTPException(status_code=404, detail="job not found")
        return {"status": "ok", "id": job_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error heartbeating job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue", response_class=JSONResponse)
async def list_queue(status: str = None, execution_id: str = None, worker_id: str = None, limit: int = 100):
    try:
        filters = []
        params: list[Any] = []
        if status:
            filters.append("status = %s")
            params.append(status)
        if execution_id:
            filters.append("execution_id = %s")
            params.append(execution_id)
        if worker_id:
            filters.append("worker_id = %s")
            params.append(worker_id)
        where = f"WHERE {' AND '.join(filters)}" if filters else ''
        with get_db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(f"SELECT * FROM noetl.queue {where} ORDER BY priority DESC, id LIMIT %s", params + [limit])
                rows = cur.fetchall()
        for r in rows:
            if r.get('input_context') is None:
                r['input_context'] = {}
        return {"status": "ok", "items": rows}
    except Exception as e:
        logger.exception(f"Error listing queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue/size", response_class=JSONResponse)
async def queue_size(status: str = "queued"):
    """Return the number of jobs in the queue for a given status."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM noetl.queue WHERE status = %s", (status,))
                row = cur.fetchone()
        return {"status": "ok", "count": row[0] if row else 0}
    except Exception as e:
        logger.exception(f"Error fetching queue size: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/enqueue")
async def enqueue_job(request: Request):
    body = await request.json()
    execution_id = body.get("execution_id")
    node_id = body.get("node_id")
    action = body.get("action")
    input_context = body.get("input_context", {})
    priority = int(body.get("priority", 0))
    max_attempts = int(body.get("max_attempts", 5))
    available_at = body.get("available_at")
    if not execution_id or not node_id or not action:
        raise HTTPException(status_code=400, detail="execution_id, node_id, action required")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO noetl.queue (execution_id, node_id, action, input_context, priority, max_attempts, available_at)
                VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)
                RETURNING id
                """,
                (execution_id, node_id, action, json.dumps(input_context), priority, max_attempts, available_at)
            )
            row = cur.fetchone()
            conn.commit()
    return {"job_id": row[0]}

@router.post("/queue/reserve")
async def reserve_job(request: Request):
    body = await request.json()
    worker_id = body.get("worker_id")
    lease_seconds = int(body.get("lease_seconds", 60))
    if not worker_id:
        raise HTTPException(status_code=400, detail="worker_id required")
    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                WITH cte AS (
                  SELECT id FROM noetl.queue
                  WHERE status='queued' AND available_at <= now()
                  ORDER BY priority DESC, id
                  FOR UPDATE SKIP LOCKED
                  LIMIT 1
                )
                UPDATE noetl.queue q
                SET status='leased',
                    worker_id=%s,
                    lease_until=now() + (%s || ' seconds')::interval,
                    last_heartbeat=now(),
                    attempts = q.attempts + 1
                FROM cte
                WHERE q.id = cte.id
                RETURNING q.*;
                """,
                (worker_id, str(lease_seconds))
            )
            job = cur.fetchone()
            conn.commit()
    if not job:
        return {"job": None}
    if job.get("input_context") is None:
        job["input_context"] = {}
    return {"job": job}

@router.post("/queue/heartbeat")
async def heartbeat_job(request: Request):
    body = await request.json()
    job_id = body.get("job_id")
    worker_id = body.get("worker_id")
    extend_seconds = body.get("extend_seconds")
    if not job_id or not worker_id:
        raise HTTPException(status_code=400, detail="job_id, worker_id required")
    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT worker_id FROM noetl.queue WHERE id = %s", (job_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="job not found")
            if row.get("worker_id") != worker_id:
                raise HTTPException(status_code=409, detail="worker mismatch")
            if extend_seconds:
                cur.execute(
                    "UPDATE noetl.queue SET last_heartbeat=now(), lease_until = now() + (%s || ' seconds')::interval WHERE id = %s",
                    (str(int(extend_seconds)), job_id)
                )
            else:
                cur.execute("UPDATE noetl.queue SET last_heartbeat=now() WHERE id = %s", (job_id,))
            conn.commit()
    return {"ok": True}

@router.post("/queue/ack")
async def ack_job(request: Request):
    body = await request.json()
    job_id = body.get("job_id")
    worker_id = body.get("worker_id")
    if not job_id or not worker_id:
        raise HTTPException(status_code=400, detail="job_id, worker_id required")
    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT worker_id FROM noetl.queue WHERE id = %s", (job_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="job not found")
            if row.get("worker_id") != worker_id:
                raise HTTPException(status_code=409, detail="worker mismatch")
            cur.execute("UPDATE noetl.queue SET status='done', lease_until=NULL WHERE id = %s", (job_id,))
            conn.commit()
    return {"ok": True}

@router.post("/queue/nack")
async def nack_job(request: Request):
    body = await request.json()
    job_id = body.get("job_id")
    worker_id = body.get("worker_id")
    retry_delay_seconds = int(body.get("retry_delay_seconds", 60))
    if not job_id or not worker_id:
        raise HTTPException(status_code=400, detail="job_id, worker_id required")
    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT worker_id, attempts, max_attempts FROM noetl.queue WHERE id = %s", (job_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="job not found")
            if row.get("worker_id") != worker_id:
                raise HTTPException(status_code=409, detail="worker mismatch")
            attempts = row.get("attempts", 0)
            max_attempts = row.get("max_attempts", 5)
            if attempts >= max_attempts:
                cur.execute("UPDATE noetl.queue SET status='dead' WHERE id = %s", (job_id,))
            else:
                cur.execute(
                    "UPDATE noetl.queue SET status='queued', worker_id=NULL, lease_until=NULL, available_at = now() + (%s || ' seconds')::interval WHERE id = %s",
                    (str(retry_delay_seconds), job_id)
                )
            conn.commit()
    return {"ok": True}

@router.post("/queue/reap-expired")
async def reap_expired_jobs():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE noetl.queue
                SET status='queued', worker_id=NULL, lease_until=NULL
                WHERE status='leased' AND lease_until IS NOT NULL AND lease_until < now()
                RETURNING id
                """
            )
            rows = cur.fetchall()
            conn.commit()
    return {"reclaimed": len(rows)}
