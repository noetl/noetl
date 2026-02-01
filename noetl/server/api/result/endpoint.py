"""
Result Storage API endpoints.

REST API for result storage operations:
- PUT /api/result/{execution_id} - Store result data
- GET /api/result/{execution_id}/{step_name} - Get result by step name
- GET /api/result/resolve - Resolve any ref to data
- GET /api/result/{execution_id}/list - List all results
- DELETE /api/result/{execution_id} - Cleanup execution results

This is the preferred API - /api/temp is maintained for backwards compatibility.
"""

from fastapi import APIRouter, HTTPException, Query, Body
from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field

from noetl.core.storage import (
    ResultStore,
    ResultRef,
    Scope,
    StoreTier,
    default_store,
    default_gc,
    default_tracker,
)
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)

router = APIRouter(prefix="/api/result", tags=["result"])


# === Request/Response Models ===

class ResultPutRequest(BaseModel):
    """Request to store result data."""
    name: str = Field(..., description="Logical name for the result (usually step name)")
    data: Any = Field(..., description="Data to store (any JSON-serializable type)")
    scope: Optional[str] = Field(default="execution", description="Scope: step, execution, workflow, permanent")
    store: Optional[str] = Field(default=None, description="Storage tier: memory, kv, object, s3, gcs, db")
    ttl: Optional[str] = Field(default=None, description="TTL: '30m', '1h', '1d', 'forever'")
    source_step: Optional[str] = Field(default=None, description="Step that created this result")
    correlation: Optional[Dict[str, Any]] = Field(default=None, description="Loop/pagination tracking")
    extracted: Optional[Dict[str, Any]] = Field(default=None, description="Extracted fields from output.select")
    compress: bool = Field(default=False, description="Compress data")


class ResultPutResponse(BaseModel):
    """Response from result put."""
    ref: str = Field(..., description="ResultRef URI")
    store: str = Field(..., description="Storage tier used")
    scope: str = Field(..., description="Lifecycle scope")
    expires_at: Optional[str] = Field(default=None, description="Expiration timestamp (null for permanent scope)")
    bytes: int = Field(default=0, description="Data size in bytes")
    sha256: Optional[str] = Field(default=None, description="Content hash")


class ResultRefResponse(BaseModel):
    """ResultRef metadata response."""
    ref: str
    store: str
    scope: str
    name: str
    expires_at: Optional[str] = None
    bytes: int = 0
    sha256: Optional[str] = None
    preview: Optional[Dict[str, Any]] = None
    extracted: Optional[Dict[str, Any]] = None
    correlation: Optional[Dict[str, Any]] = None


class ResultListResponse(BaseModel):
    """Response for listing results."""
    execution_id: str
    count: int
    refs: List[ResultRefResponse]


class CleanupResponse(BaseModel):
    """Response from cleanup operations."""
    execution_id: str
    deleted: int
    scope: str


# === Helper Functions ===

def parse_ttl(ttl_str: Optional[str]) -> Optional[int]:
    """Parse TTL string to seconds. Returns None for 'forever'."""
    if not ttl_str:
        return None
    if ttl_str.lower() in ('forever', '-1', 'permanent'):
        return None  # No expiry

    # Parse duration string (30m, 1h, 2d, 1y)
    ttl_str = ttl_str.strip().lower()
    multipliers = {
        's': 1,
        'm': 60,
        'h': 3600,
        'd': 86400,
        'w': 604800,
        'y': 31536000,
    }

    for suffix, mult in multipliers.items():
        if ttl_str.endswith(suffix):
            try:
                return int(ttl_str[:-1]) * mult
            except ValueError:
                return None

    # Try as integer seconds
    try:
        return int(ttl_str)
    except ValueError:
        return None


# === Endpoints ===

@router.put("/{execution_id}")
async def put_result(
    execution_id: str,
    request: ResultPutRequest = Body(...)
) -> ResultPutResponse:
    """
    Store result data and return ResultRef.

    The data is stored in the appropriate backend based on size and scope.
    Returns a ResultRef pointer that can be used in subsequent steps.

    Scopes:
    - step: Cleaned when step completes
    - execution: Cleaned when playbook completes
    - workflow: Cleaned when root playbook completes
    - permanent: Never auto-cleaned
    """
    try:
        # Parse scope
        scope_str = request.scope or "execution"
        try:
            scope = Scope(scope_str)
        except ValueError:
            raise HTTPException(400, f"Invalid scope: {scope_str}. Use: step, execution, workflow, permanent")

        # Parse store tier
        store = None
        if request.store:
            try:
                store = StoreTier(request.store)
            except ValueError:
                raise HTTPException(400, f"Invalid store tier: {request.store}")

        # Parse TTL
        ttl_seconds = parse_ttl(request.ttl)

        # Store the data
        result_ref = await default_store.put(
            execution_id=execution_id,
            name=request.name,
            data=request.data,
            scope=scope,
            store=store,
            ttl_seconds=ttl_seconds,
            source_step=request.source_step,
            correlation=request.correlation,
            compress=request.compress
        )

        # Register with scope tracker
        default_tracker.register_ref(
            result_ref,
            execution_id=execution_id,
            step_name=request.source_step
        )

        return ResultPutResponse(
            ref=result_ref.ref,
            store=result_ref.store.value,
            scope=result_ref.scope.value,
            expires_at=result_ref.expires_at.isoformat() if result_ref.expires_at else None,
            bytes=result_ref.meta.bytes,
            sha256=result_ref.meta.sha256
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"RESULT API: Put failed: {e}")
        raise HTTPException(500, str(e))


@router.get("/{execution_id}/{step_name}")
async def get_result_by_step(
    execution_id: str,
    step_name: str,
    resolve: bool = Query(default=True, description="Resolve to data or return ref metadata")
) -> Any:
    """
    Get result data by execution ID and step name.

    If resolve=True (default), returns the actual data.
    If resolve=False, returns the ResultRef metadata.
    """
    try:
        # Find matching refs
        refs = await default_store.list_refs(execution_id)
        matching = [r for r in refs if step_name in r.ref]

        if not matching:
            raise HTTPException(404, f"Result not found for step: {step_name}")

        # Get most recent
        ref = matching[-1]

        if resolve:
            return await default_store.get(ref)
        else:
            return ResultRefResponse(
                ref=ref.ref,
                store=ref.store.value,
                scope=ref.scope.value,
                name=step_name,
                expires_at=ref.expires_at.isoformat() if ref.expires_at else None,
                bytes=ref.meta.bytes,
                sha256=ref.meta.sha256,
                preview=ref.preview,
                extracted=getattr(ref, 'extracted', None),
                correlation=ref.correlation
            )

    except HTTPException:
        raise
    except KeyError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"RESULT API: Get failed: {e}")
        raise HTTPException(500, str(e))


@router.get("/resolve")
async def resolve_ref(
    ref: str = Query(..., description="ResultRef URI to resolve")
) -> Any:
    """
    Resolve a ResultRef to its data.

    Accepts any ref type:
    - ResultRef URI (noetl://execution/...)
    - TempRef URI (legacy, noetl://execution/.../tmp/...)
    - Inline data
    """
    try:
        return await default_store.resolve(ref)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"RESULT API: Resolve failed: {e}")
        raise HTTPException(500, str(e))


@router.get("/{execution_id}/list")
async def list_results(
    execution_id: str,
    scope: Optional[str] = Query(default=None, description="Filter by scope"),
    step_name: Optional[str] = Query(default=None, description="Filter by step name")
) -> ResultListResponse:
    """
    List all results for an execution.

    Optionally filter by scope or step name.
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

        # Filter by step name if provided
        if step_name:
            refs = [r for r in refs if step_name in r.ref]

        return ResultListResponse(
            execution_id=execution_id,
            count=len(refs),
            refs=[
                ResultRefResponse(
                    ref=r.ref,
                    store=r.store.value,
                    scope=r.scope.value,
                    name=r.ref.split("/")[-2] if "/" in r.ref else "unknown",
                    expires_at=r.expires_at.isoformat() if r.expires_at else None,
                    bytes=r.meta.bytes,
                    sha256=r.meta.sha256,
                    preview=r.preview,
                    extracted=getattr(r, 'extracted', None),
                    correlation=r.correlation
                )
                for r in refs
            ]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"RESULT API: List failed: {e}")
        raise HTTPException(500, str(e))


@router.delete("/{execution_id}")
async def cleanup_execution(
    execution_id: str,
    scope: str = Query(default="execution", description="Scope to clean: step, execution, workflow")
) -> CleanupResponse:
    """
    Clean up all results for an execution.

    Note: 'permanent' scope results are never auto-cleaned. Use explicit delete.
    """
    try:
        scope_enum = Scope(scope)

        if scope_enum == Scope.PERMANENT:
            raise HTTPException(400, "Cannot bulk-clean 'permanent' scope. Delete individual refs instead.")

        if scope_enum == Scope.WORKFLOW:
            deleted = await default_gc.cleanup_workflow(execution_id)
        elif scope_enum == Scope.EXECUTION:
            deleted = await default_gc.cleanup_execution(execution_id)
        else:
            # Step cleanup requires step_name
            raise HTTPException(400, "Step cleanup requires step_name parameter. Use DELETE /{execution_id}/step/{step_name}")

        return CleanupResponse(
            execution_id=execution_id,
            deleted=deleted,
            scope=scope
        )

    except ValueError:
        raise HTTPException(400, f"Invalid scope: {scope}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"RESULT API: Cleanup failed: {e}")
        raise HTTPException(500, str(e))


@router.delete("/{execution_id}/step/{step_name}")
async def cleanup_step(
    execution_id: str,
    step_name: str
) -> CleanupResponse:
    """
    Clean up step-scoped results when step completes.
    """
    try:
        deleted = await default_gc.cleanup_step(execution_id, step_name)

        return CleanupResponse(
            execution_id=execution_id,
            deleted=deleted,
            scope="step"
        )

    except Exception as e:
        logger.error(f"RESULT API: Step cleanup failed: {e}")
        raise HTTPException(500, str(e))


@router.get("/stats")
async def get_stats() -> Dict[str, Any]:
    """
    Get result storage statistics.

    Returns GC stats and scope tracking info.
    """
    return default_gc.get_stats()
