from fastapi import APIRouter, HTTPException
from noetl.shared import setup_logger
logger = setup_logger(__name__, include_location=True)
router = APIRouter()

@router.post("/playbook/register")
def register_playbook(payload: dict):
    try:
        return {"message": "Playbook registered"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
