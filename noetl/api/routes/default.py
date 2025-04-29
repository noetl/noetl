from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from noetl.util import setup_logger
from noetl.config.settings import AppConfig

logger = setup_logger(__name__, include_location=True)
app_config = AppConfig()
templates = Jinja2Templates(directory=app_config.templates_dir)
router = APIRouter()



@router.get("/health", response_class=JSONResponse)
def health_check():
    return {"status": "ok"}


@router.get("/health-dashboard", response_class=HTMLResponse)
async def health_dashboard():
    return """
    <div class="health-status-container">
        <span class="health-indicator"></span>
        <span class="health-text">Service is healthy</span>
    </div>
    """

@router.get("/", response_class=HTMLResponse)
async def main_page(request: Request):
    return templates.TemplateResponse("main.html", {"request": request})
