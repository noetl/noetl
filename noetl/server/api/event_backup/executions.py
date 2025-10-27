"""
Execution query endpoints - all GET endpoints for execution data.

These endpoints query and aggregate event data to provide execution views.
Business logic is in event/service/event_service.py.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from noetl.core.logger import setup_logger
from noetl.core.common import convert_snowflake_ids_for_api
from .service import get_event_service

logger = setup_logger(__name__, include_location=True)
router = APIRouter()


@router.get("/execution/data/{execution_id}", response_class=JSONResponse)
async def get_execution_data(
    request: Request,
    execution_id: str
):
    """Get execution data by ID"""
    try:
        event_service = get_event_service()
        event = await event_service.get_event(execution_id)
        if not event:
            raise HTTPException(
                status_code=404,
                detail=f"Execution '{execution_id}' not found."
            )
        return event

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching execution data: {e}.")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching execution data: {e}."
        )


@router.get("/events/summary/{execution_id}", response_class=JSONResponse)
async def get_execution_summary(request: Request, execution_id: str):
    """
    Summarize execution events by type and provide quick success/error/skipped counts.
    """
    try:
        event_service = get_event_service()
        summary = await event_service.get_execution_summary(execution_id)
        return JSONResponse(content={"status": "ok", "summary": summary})
        
    except Exception as e:
        logger.exception(f"Error summarizing execution: {e}.")
        return JSONResponse(content={"status": "error", "error": str(e)}, status_code=500)


@router.get("/executions", response_class=JSONResponse)
async def get_executions():
    """Get all executions"""
    try:
        event_service = get_event_service()
        executions = await event_service.get_all_executions()
        # Convert snowflake IDs to strings for API compatibility
        executions = convert_snowflake_ids_for_api(executions)
        return executions
    except Exception as e:
        logger.error(f"Error getting executions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/executions/{execution_id}", response_class=JSONResponse)
async def get_execution(execution_id: str):
    """Get execution by ID with full event history"""
    try:
        event_service = get_event_service()
        execution = await event_service.get_execution_detail(execution_id)

        if not execution:
            raise HTTPException(
                status_code=404,
                detail=f"Execution '{execution_id}' not found."
            )

        # Convert snowflake IDs to strings for API compatibility
        execution = convert_snowflake_ids_for_api(execution)
        return execution

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching execution: {e}.")
        raise HTTPException(status_code=500, detail=str(e))
