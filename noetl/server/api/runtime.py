from typing import Optional
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from noetl.logger import setup_logger

logger = setup_logger(__name__, include_location=True)
router = APIRouter()


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
