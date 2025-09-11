from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


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
