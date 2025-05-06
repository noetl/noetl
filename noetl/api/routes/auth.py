from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from noetl.ctx.app_context import get_app_context, AppContext
from noetl.config.settings import AppConfig
from noetl.util import setup_logger
logger = setup_logger(__name__, include_location=True)
app_config = AppConfig()
# templates = Jinja2Templates(directory=app_config.get_template_folder("auth"))
router = APIRouter(prefix="/auth")