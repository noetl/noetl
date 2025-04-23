from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from noetl.shared.logger import setup_logger

logger = setup_logger(__name__, include_location=True)

router = APIRouter()

@router.get("/")
def index():
    return RedirectResponse(url="/docs")


@router.get("/health")
def health_check():
    return {"status": "ok"}

