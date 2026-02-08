"""
NoETL Runtime API Endpoints - FastAPI routes for runtime component management.

Provides REST endpoints for:
- Worker pool registration, deregistration, heartbeat, and listing
- Generic runtime component management
- Broker registration (placeholder for future implementation)
"""

from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from noetl.core.logger import setup_logger
from .schema import (
    WorkerPoolRegistrationRequest,
    RuntimeRegistrationResponse,
    RuntimeDeregistrationRequest,
    RuntimeHeartbeatRequest,
    RuntimeHeartbeatResponse,
    RuntimeListResponse
)
from .service import RuntimeService

logger = setup_logger(__name__, include_location=True)
router = APIRouter()


# ============================================================================
# Worker Pool Endpoints
# ============================================================================

@router.post("/worker/pool/register", response_model=RuntimeRegistrationResponse)
async def register_worker_pool(request: WorkerPoolRegistrationRequest) -> RuntimeRegistrationResponse:
    """
    Register or update a worker pool in the runtime registry.
    
    **Request Body**:
    ```json
    {
        "name": "worker-pool-01",
        "runtime": "python",
        "status": "ready",
        "capacity": 10,
        "labels": {"env": "prod"},
        "pid": 12345,
        "hostname": "worker-node-1"
    }
    ```
    
    **Response**:
    ```json
    {
        "status": "ok",
        "name": "worker-pool-01",
        "runtime": "python",
        "runtime_id": "123456789"
    }
    ```
    """
    try:
        return await RuntimeService.register_component(request)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error registering worker pool: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/worker/pool/deregister", response_model=RuntimeRegistrationResponse)
async def deregister_worker_pool(request: Request) -> RuntimeRegistrationResponse:
    """
    Deregister a worker pool by name (marks as offline).
    
    **Request Body**:
    ```json
    {
        "name": "worker-pool-01"
    }
    ```
    """
    logger.info("Worker deregister endpoint called")
    try:
        body = await request.json()
        deregister_request = RuntimeDeregistrationRequest(
            name=body.get("name"),
            kind="worker_pool"
        )
        logger.info(f"Deregistering worker pool: {deregister_request.name}")
        
        result = await RuntimeService.deregister_component(deregister_request)
        logger.info(f"Worker deregistration completed for: {deregister_request.name}")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error deregistering worker pool: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Compatibility: some workers use POST instead of DELETE
@router.post("/worker/pool/deregister", response_model=RuntimeRegistrationResponse)
async def deregister_worker_pool_post(request: Request) -> RuntimeRegistrationResponse:
    """
    POST alternative for worker pool deregistration (backward compatibility).
    """
    return await deregister_worker_pool(request)


@router.post("/worker/pool/heartbeat", response_model=RuntimeHeartbeatResponse)
async def heartbeat_worker_pool(request: Request) -> RuntimeHeartbeatResponse:
    """
    Persist heartbeat for a worker pool.
    
    **Request Body (minimal)**:
    ```json
    {
        "name": "worker-pool-01"
    }
    ```
    
    **Optional for auto-recreation**:
    ```json
    {
        "name": "worker-pool-01",
        "registration": {
            "name": "worker-pool-01",
            "runtime": "python",
            "capacity": 10
        }
    }
    ```
    
    **Response**:
    - `200 OK`: `{"status": "ok", "name": "worker-pool-01", "runtime_id": "123"}`
    - `404 Not Found`: Component not registered, re-registration required
    - `200 OK` with `status: "recreated"`: Component was auto-recreated from registration data
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    
    heartbeat_request = RuntimeHeartbeatRequest(**body)
    
    try:
        return await RuntimeService.process_heartbeat(heartbeat_request)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error processing heartbeat: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/worker/pools", response_model=RuntimeListResponse)
async def list_worker_pools(
    runtime: Optional[str] = None,
    status: Optional[str] = None
) -> RuntimeListResponse:
    """
    List all registered worker pools from the runtime table.
    
    **Query Parameters**:
    - `runtime`: Filter by runtime type (e.g., "python", "nodejs")
    - `status`: Filter by status (e.g., "ready", "offline", "busy")
    
    **Response**:
    ```json
    {
        "items": [
            {
                "name": "worker-pool-01",
                "runtime": {"type": "python", "pid": 12345},
                "status": "ready",
                "capacity": 10,
                "labels": {"env": "prod"},
                "heartbeat": "2025-10-12T10:30:00",
                "created_at": "2025-10-12T09:00:00",
                "updated_at": "2025-10-12T10:30:00"
            }
        ],
        "count": 1,
        "runtime": "python",
        "status": "ready"
    }
    ```
    """
    try:
        return await RuntimeService.list_components(
            kind="worker_pool",
            runtime=runtime,
            status=status
        )
    except Exception as e:
        logger.exception(f"Error listing worker pools: {e}")
        # Return empty list with error instead of raising exception
        from .schema import RuntimeListResponse
        return RuntimeListResponse(
            items=[],
            count=0,
            runtime=runtime,
            status=status,
            error=str(e)
        )


