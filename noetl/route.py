from fastapi import APIRouter, HTTPException
from noetl.job import Job
from noetl.logger import setup_logger

logger = setup_logger(__name__, include_location=True)

router = APIRouter()


@router.get("/")
def index():
    return {"message": "NoETL Service listening!"}


@router.get("/health")
def health_check():
    return {"status": "ok"}


@router.post("/jobs")
async def run_job(payload: dict):
    try:
        job = Job(payload)
        results = await job.execute()
        return {"status": "success", "results": results}
    except Exception as e:
        logger.error(f"NoETL API job failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
