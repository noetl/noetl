from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/events")

@router.get("/", response_class=HTMLResponse)
async def events_page():
    return """
    <div>
        <h2>Events Page</h2>
        <p>Track events.</p>
    </div>
    """
