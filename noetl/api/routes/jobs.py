from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/jobs")

@router.get("/", response_class=HTMLResponse)
async def jobs_page():
    return """
    <div>
        <h2>Jobs Page</h2>
        <p>Discover job entries and workflow execution details.</p>
    </div>
    """
