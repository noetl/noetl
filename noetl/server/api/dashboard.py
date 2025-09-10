from fastapi import APIRouter
from fastapi.responses import JSONResponse
from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks
from noetl.core.logger import setup_logger


logger = setup_logger(__name__, include_location=True)
router = APIRouter()

@router.get("/dashboard/stats", response_class=JSONResponse)
async def get_dashboard_stats():
    """Get dashboard statistics"""
    try:
        return {
            "total_executions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
            "total_playbooks": 0,
            "active_workflows": 0
        }
    except Exception as e:
        logger.error(f"Error getting dashboard stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dashboard/widgets", response_class=JSONResponse)
async def get_dashboard_widgets():
    """Get dashboard widgets"""
    try:
        return []
    except Exception as e:
        logger.error(f"Error getting dashboard widgets: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard/stats", response_class=JSONResponse)
async def get_dashboard_stats():
    return JSONResponse(content={"status": "ok", "stats": {}})


@router.get("/dashboard/widgets", response_class=JSONResponse)
async def get_dashboard_widgets():
    return JSONResponse(content={"widgets": []})


@router.get("/executions", response_class=JSONResponse)
async def get_executions():
    return JSONResponse(content={"executions": []})


@router.get("/executions/{execution_id}", response_class=JSONResponse)
async def get_execution(execution_id: str):
    return JSONResponse(content={"execution_id": execution_id})


@router.get("/health", response_class=JSONResponse)
async def api_health():
    return JSONResponse(content={"status": "ok"})
