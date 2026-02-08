"""
TempRef API endpoints.

REST API for temp storage operations:
- PUT /api/temp/{execution_id} - Store temp data
- GET /api/temp/{execution_id}/{name} - Get temp by name
- GET /api/temp/resolve - Resolve any ref to data
- GET /api/temp/{execution_id}/list - List all temps
- DELETE /api/temp/{execution_id} - Cleanup execution temps
"""

from fastapi import APIRouter, HTTPException, Query, Body
from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field

from noetl.core.storage import (
    TempStore,
    TempRef,
    Scope,
    StoreTier,
    default_store,
    default_gc,
    default_tracker,
)
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)

router = APIRouter(prefix="/api/temp", tags=["temp"])


# === Request/Response Models ===

class TempPutRequest(BaseModel):
    """Request to store temp data."""
    name: str = Field(..., description="Logical name for the temp")
    data: Any = Field(..., description="Data to store (any JSON-serializable type)")
    scope: Optional[str] = Field(default="execution", description="Scope: step, execution, workflow")
    store: Optional[str] = Field(default=None, description="Storage tier: memory, kv, object, s3, gcs, db")
    ttl_seconds: Optional[int] = Field(default=None, description="TTL in seconds")
    source_step: Optional[str] = Field(default=None, description="Step that created this temp")
    correlation: Optional[Dict[str, Any]] = Field(default=None, description="Loop/pagination tracking")
    compress: bool = Field(default=False, description="Compress data")


class TempPutResponse(BaseModel):
    """Response from temp put."""
    ref: str = Field(..., description="TempRef URI")
    store: str = Field(..., description="Storage tier used")
    scope: str = Field(..., description="Lifecycle scope")
    expires_at: Optional[str] = Field(default=None, description="Expiration timestamp")
    bytes: int = Field(default=0, description="Data size in bytes")
    sha256: Optional[str] = Field(default=None, description="Content hash")


class TempRefResponse(BaseModel):
    """TempRef metadata response."""
    ref: str
    store: str
    scope: str
    name: str
    expires_at: Optional[str] = None
    bytes: int = 0
    sha256: Optional[str] = None
    preview: Optional[Dict[str, Any]] = None
    correlation: Optional[Dict[str, Any]] = None


class TempListResponse(BaseModel):
    """Response for listing temps."""
    execution_id: str
    count: int
    refs: List[TempRefResponse]


class CleanupResponse(BaseModel):
    """Response from cleanup operations."""
    execution_id: str
    deleted: int
    scope: str


# === Endpoints ===

@router.put("/{execution_id}")
async def put_temp(
    execution_id: str,
    request: TempPutRequest = Body(...)
) -> TempPutResponse:
    """
    Store temp data and return TempRef.

    The data is stored in the appropriate backend based on size and scope.
    Returns a TempRef pointer that can be used in subsequent steps.
    """
    try:
        # Parse scope
        scope = Scope(request.scope) if request.scope else Scope.EXECUTION

        # Parse store tier
        store = None
        if request.store:
            try:
                store = StoreTier(request.store)
            except ValueError:
                raise HTTPException(400, f"Invalid store tier: {request.store}")

        # Store the data
        temp_ref = await default_store.put(
            execution_id=execution_id,
            name=request.name,
            data=request.data,
            scope=scope,
            store=store,
            ttl_seconds=request.ttl_seconds,
            source_step=request.source_step,
            correlation=request.correlation,
            compress=request.compress
        )

        # Register with scope tracker
        default_tracker.register_ref(
            temp_ref,
            execution_id=execution_id,
            step_name=request.source_step
        )

        return TempPutResponse(
            ref=temp_ref.ref,
            store=temp_ref.store.value,
            scope=temp_ref.scope.value,
            expires_at=temp_ref.expires_at.isoformat() if temp_ref.expires_at else None,
            bytes=temp_ref.meta.bytes,
            sha256=temp_ref.meta.sha256
        )

    except Exception as e:
        logger.error(f"TEMP API: Put failed: {e}")
        raise HTTPException(500, str(e))


@router.get("/{execution_id}/{name}")
async def get_temp_by_name(
    execution_id: str,
    name: str,
    resolve: bool = Query(default=True, description="Resolve to data or return ref metadata")
) -> Any:
    """
    Get temp data by execution ID and name.

    If resolve=True (default), returns the actual data.
    If resolve=False, returns the TempRef metadata.
    """
    try:
        # Find matching refs
        refs = await default_store.list_refs(execution_id)
        matching = [r for r in refs if name in r.ref]

        if not matching:
            raise HTTPException(404, f"TempRef not found: {name}")

        # Get most recent
        ref = matching[-1]

        if resolve:
            return await default_store.get(ref)
        else:
            return TempRefResponse(
                ref=ref.ref,
                store=ref.store.value,
                scope=ref.scope.value,
                name=name,
                expires_at=ref.expires_at.isoformat() if ref.expires_at else None,
                bytes=ref.meta.bytes,
                sha256=ref.meta.sha256,
                preview=ref.preview,
                correlation=ref.correlation
            )

    except HTTPException:
        raise
    except KeyError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"TEMP API: Get failed: {e}")
        raise HTTPException(500, str(e))


@router.get("/resolve")
async def resolve_ref(
    ref: str = Query(..., description="TempRef URI to resolve")
) -> Any:
    """
    Resolve a TempRef to its data.

    Accepts any ref type:
    - TempRef URI (noetl://execution/...)
    - ResultRef
    - Inline data
    """
    try:
        return await default_store.resolve(ref)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"TEMP API: Resolve failed: {e}")
        raise HTTPException(500, str(e))


@router.get("/{execution_id}/list")
async def list_temps(
    execution_id: str,
    scope: Optional[str] = Query(default=None, description="Filter by scope"),
    source_step: Optional[str] = Query(default=None, description="Filter by source step")
) -> TempListResponse:
    """
    List all TempRefs for an execution.

    Optionally filter by scope or source step.
    """
    try:
        # Parse scope filter
        scope_filter = None
        if scope:
            try:
                scope_filter = Scope(scope)
            except ValueError:
                raise HTTPException(400, f"Invalid scope: {scope}")

        refs = await default_store.list_refs(execution_id, scope=scope_filter)

        # Filter by source step if provided
        # Note: This is a simple filter since source_step isn't tracked in current impl
        # TODO: Add source_step tracking to TempRef

        return TempListResponse(
            execution_id=execution_id,
            count=len(refs),
            refs=[
                TempRefResponse(
                    ref=r.ref,
                    store=r.store.value,
                    scope=r.scope.value,
                    name=r.ref.split("/")[-2] if "/" in r.ref else "unknown",
                    expires_at=r.expires_at.isoformat() if r.expires_at else None,
                    bytes=r.meta.bytes,
                    sha256=r.meta.sha256,
                    preview=r.preview,
                    correlation=r.correlation
                )
                for r in refs
            ]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TEMP API: List failed: {e}")
        raise HTTPException(500, str(e))


@router.delete("/{execution_id}")
async def cleanup_execution(
    execution_id: str,
    scope: str = Query(default="execution", description="Scope to clean: step, execution, workflow")
) -> CleanupResponse:
    """
    Clean up all temps for an execution.

    Called when execution completes to free up storage.
    """
    try:
        scope_enum = Scope(scope)

        if scope_enum == Scope.WORKFLOW:
            deleted = await default_gc.cleanup_workflow(execution_id)
        elif scope_enum == Scope.EXECUTION:
            deleted = await default_gc.cleanup_execution(execution_id)
        else:
            # Step cleanup requires step_name
            raise HTTPException(400, "Step cleanup requires step_name parameter")

        return CleanupResponse(
            execution_id=execution_id,
            deleted=deleted,
            scope=scope
        )

    except ValueError:
        raise HTTPException(400, f"Invalid scope: {scope}")
    except Exception as e:
        logger.error(f"TEMP API: Cleanup failed: {e}")
        raise HTTPException(500, str(e))


@router.delete("/{execution_id}/step/{step_name}")
async def cleanup_step(
    execution_id: str,
    step_name: str
) -> CleanupResponse:
    """
    Clean up step-scoped temps when step completes.
    """
    try:
        deleted = await default_gc.cleanup_step(execution_id, step_name)

        return CleanupResponse(
            execution_id=execution_id,
            deleted=deleted,
            scope="step"
        )

    except Exception as e:
        logger.error(f"TEMP API: Step cleanup failed: {e}")
        raise HTTPException(500, str(e))


@router.get("/stats")
async def get_stats() -> Dict[str, Any]:
    """
    Get temp storage statistics.

    Returns GC stats and scope tracking info.
    """
    return default_gc.get_stats()
