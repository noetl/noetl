"""
NoETL Queue API Endpoints - FastAPI routes for queue operations.

Provides REST endpoints for:
- Job enqueuing and leasing
- Job completion and failure handling
- Heartbeat and lease management
- Queue listing and statistics
- Expired job reclamation
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from noetl.core.logger import setup_logger
from .service import QueueService

logger = setup_logger(__name__, include_location=True)
router = APIRouter(tags=["Queue"])


@router.post("/queue/enqueue", response_class=JSONResponse)
async def enqueue_job(request: Request):
    """
    Enqueue a job into the noetl.queue table.
    
    **Request Body**:
    ```json
    {
        "execution_id": "123456789",
        "node_id": "step-1",
        "action": "python",
        "context": {"key": "value"},
        "priority": 0,
        "max_attempts": 5,
        "available_at": "2025-10-12T10:00:00Z"
    }
    ```
    
    **Note**: `input_context` is supported for backward compatibility.
    
    **Response**:
    ```json
    {
        "status": "ok",
        "id": 123
    }
    ```
    """
    try:
        body = await request.json()
        execution_id = body.get("execution_id")
        node_id = body.get("node_id")
        action = body.get("action")
        context = body.get("context")
        input_context = body.get("input_context")
        priority = int(body.get("priority", 0))
        max_attempts = int(body.get("max_attempts", 5))
        available_at = body.get("available_at")
        
        if not execution_id or not node_id or not action:
            raise HTTPException(
                status_code=400,
                detail="execution_id, node_id and action are required"
            )
        
        result = await QueueService.enqueue_job(
            execution_id=execution_id,
            node_id=node_id,
            action=action,
            context=context,
            input_context=input_context,
            priority=priority,
            max_attempts=max_attempts,
            available_at=available_at
        )
        return result.model_dump()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error enqueueing job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/lease", response_class=JSONResponse)
async def lease_job(request: Request):
    """
    Atomically lease a queued job for a worker.
    
    Returns queued job or `{status: 'empty'}` when nothing available.
    
    **Request Body**:
    ```json
    {
        "worker_id": "worker-01",
        "lease_seconds": 60
    }
    ```
    
    **Response (with job)**:
    ```json
    {
        "status": "ok",
        "job": {
            "queue_id": 123,
            "execution_id": "123456789",
            "node_id": "step-1",
            "action": "python",
            "context": {"key": "value"},
            ...
        }
    }
    ```
    
    **Response (empty)**:
    ```json
    {
        "status": "empty"
    }
    ```
    """
    try:
        body = await request.json()
        worker_id = body.get("worker_id")
        lease_seconds = int(body.get("lease_seconds", 60))
        
        if not worker_id:
            raise HTTPException(status_code=400, detail="worker_id is required")
        
        result = await QueueService.lease_job(
            worker_id=worker_id,
            lease_seconds=lease_seconds
        )
        return result.model_dump()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error leasing job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/{queue_id}/complete", response_class=JSONResponse)
async def complete_job(queue_id: int):
    """
    Mark a job completed.
    
    This endpoint also handles:
    - Loop result mapping for child executions
    - Aggregated result emission when all loop iterations complete
    - Broker evaluation triggering for continued execution
    
    **Response**:
    ```json
    {
        "status": "ok",
        "id": 123
    }
    ```
    """
    try:
        result = await QueueService.complete_job(queue_id)
        return result.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"Error completing job {queue_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/{queue_id}/fail", response_class=JSONResponse)
async def fail_job(queue_id: int, request: Request):
    """
    Mark job failed; optionally reschedule if attempts < max_attempts.
    
    If `retry` is explicitly false, mark the job as terminal 'dead' immediately.
    
    **Request Body**:
    ```json
    {
        "retry_delay_seconds": 60,
        "retry": true
    }
    ```
    
    **Response**:
    ```json
    {
        "status": "ok",
        "id": 123
    }
    ```
    """
    try:
        body = await request.json()
        retry_delay = int(body.get("retry_delay_seconds", 60))
        retry = body.get("retry", True)
        
        result = await QueueService.fail_job(
            queue_id=queue_id,
            retry_delay_seconds=retry_delay,
            retry=retry
        )
        return result.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"Error failing job {queue_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/{queue_id}/heartbeat", response_class=JSONResponse)
async def heartbeat_job(queue_id: int, request: Request):
    """
    Update heartbeat and optionally extend lease_until.
    
    **Request Body**:
    ```json
    {
        "worker_id": "worker-01",
        "extend_seconds": 60
    }
    ```
    
    **Response**:
    ```json
    {
        "status": "ok",
        "id": 123
    }
    ```
    """
    try:
        body = await request.json()
        worker_id = body.get("worker_id")
        extend = body.get("extend_seconds")
        
        result = await QueueService.heartbeat_job(
            queue_id=queue_id,
            worker_id=worker_id,
            extend_seconds=extend
        )
        return result.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"Error heartbeating job {queue_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue", response_class=JSONResponse)
async def list_queue(
    status: Optional[str] = None,
    execution_id: Optional[str] = None,
    worker_id: Optional[str] = None,
    limit: int = 100
):
    """
    List queue items with optional filtering.
    
    **Query Parameters**:
    - `status`: Filter by status (queued, leased, done, dead)
    - `execution_id`: Filter by execution ID
    - `worker_id`: Filter by worker ID
    - `limit`: Maximum results (default: 100)
    
    **Example**:
    ```
    GET /queue?status=queued&limit=50
    ```
    
    **Response**:
    ```json
    {
        "status": "ok",
        "items": [
            {
                "queue_id": 123,
                "execution_id": "123456789",
                "node_id": "step-1",
                "status": "queued",
                ...
            }
        ]
    }
    ```
    """
    try:
        result = await QueueService.list_queue(
            status=status,
            execution_id=execution_id,
            worker_id=worker_id,
            limit=limit
        )
        return result.model_dump()
    except Exception as e:
        logger.exception(f"Error listing queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue/size", response_class=JSONResponse)
async def queue_size(status: str = "queued"):
    """
    Return the number of jobs in the queue for a given status.
    
    **Query Parameters**:
    - `status`: Status to count (default: queued)
    
    **Response**:
    ```json
    {
        "status": "ok",
        "count": 42
    }
    ```
    """
    try:
        result = await QueueService.queue_size(status)
        return result.model_dump()
    except Exception as e:
        logger.exception(f"Error fetching queue size: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/queue/size", response_class=JSONResponse)
async def jobs_queue_size():
    """
    Compatibility endpoint for legacy workers expecting /jobs/queue/size.
    
    Returns the count of queued jobs.
    
    **Response**:
    ```json
    {
        "status": "ok",
        "count": 42
    }
    ```
    """
    return await queue_size(status="queued")


@router.post("/queue/reserve")
async def reserve_job(request: Request):
    """
    Reserve a job (alternative to lease with different table structure).
    
    **Request Body**:
    ```json
    {
        "worker_id": "worker-01",
        "lease_seconds": 60
    }
    ```
    
    **Response**:
    ```json
    {
        "job": {
            "id": 123,
            "execution_id": "123456789",
            ...
        }
    }
    ```
    """
    try:
        body = await request.json()
        worker_id = body.get("worker_id")
        lease_seconds = int(body.get("lease_seconds", 60))
        
        if not worker_id:
            raise HTTPException(status_code=400, detail="worker_id required")
        
        result = await QueueService.reserve_job(
            worker_id=worker_id,
            lease_seconds=lease_seconds
        )
        return result.model_dump()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error reserving job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/ack")
async def ack_job(request: Request):
    """
    Acknowledge job completion.
    
    **Request Body**:
    ```json
    {
        "queue_id": 123,
        "worker_id": "worker-01"
    }
    ```
    
    **Response**:
    ```json
    {
        "ok": true
    }
    ```
    """
    try:
        body = await request.json()
        queue_id = body.get("queue_id")
        worker_id = body.get("worker_id")
        
        if not queue_id or not worker_id:
            raise HTTPException(
                status_code=400,
                detail="queue_id, worker_id required"
            )
        
        result = await QueueService.ack_job(
            queue_id=queue_id,
            worker_id=worker_id
        )
        return result.model_dump()
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        elif "mismatch" in str(e):
            raise HTTPException(status_code=409, detail=str(e))
        else:
            raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception(f"Error acknowledging job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/nack")
async def nack_job(request: Request):
    """
    Negative acknowledgment - job failed but can retry.
    
    **Request Body**:
    ```json
    {
        "queue_id": 123,
        "worker_id": "worker-01",
        "retry_delay_seconds": 60
    }
    ```
    
    **Response**:
    ```json
    {
        "ok": true
    }
    ```
    """
    try:
        body = await request.json()
        queue_id = body.get("queue_id")
        worker_id = body.get("worker_id")
        retry_delay_seconds = int(body.get("retry_delay_seconds", 60))
        
        if not queue_id or not worker_id:
            raise HTTPException(
                status_code=400,
                detail="queue_id, worker_id required"
            )
        
        result = await QueueService.nack_job(
            queue_id=queue_id,
            worker_id=worker_id,
            retry_delay_seconds=retry_delay_seconds
        )
        return result.model_dump()
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        elif "mismatch" in str(e):
            raise HTTPException(status_code=409, detail=str(e))
        else:
            raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception(f"Error nack'ing job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/queue/reap-expired")
async def reap_expired_jobs():
    """
    Reclaim expired leased jobs back to queued status.
    
    This endpoint should be called periodically (e.g., by a cron job or
    background task) to reclaim jobs whose lease has expired.
    
    **Response**:
    ```json
    {
        "reclaimed": 5
    }
    ```
    """
    try:
        result = await QueueService.reap_expired_jobs()
        return result.model_dump()
    except Exception as e:
        logger.exception(f"Error reaping expired jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))
