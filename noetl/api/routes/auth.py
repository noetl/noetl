from fastapi import APIRouter
from noetl.config.settings import AppConfig
from noetl.util import setup_logger
logger = setup_logger(__name__, include_location=True)
app_config = AppConfig()
# templates = Jinja2Templates(directory=app_config.get_template_folder("auth"))
router = APIRouter(prefix="/auth")