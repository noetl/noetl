from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from noetl.util import setup_logger
from noetl.config.settings import AppConfig
from noetl.appctx.app_context import get_app_context, AppContext
from noetl.api.schemas.catalog import RegisterRequest
from noetl.api.services.catalog import CatalogService, create_catalog_entry
import base64
import json
import yaml

logger = setup_logger(__name__, include_location=True)
app_config = AppConfig()
templates = Jinja2Templates(directory=app_config.templates_dir)

router = APIRouter(prefix="/catalog")

def get_catalog_service():
    return CatalogService()

@router.post("/register")
async def register_resource(
    request_data: RegisterRequest,
    context: AppContext = Depends(get_app_context)
):
    content_base64 = request_data.content_base64
    logger.info("Received request to register resource.", extra={"content_base64": content_base64})
    return await CatalogService.register_entry(
        content_base64=content_base64,
        event_type="REGISTERED",
        context=context
    )

@router.get("/", response_class=HTMLResponse)
async def catalog_page(
    request: Request,
    catalog_service: CatalogService = Depends(get_catalog_service),
    context: AppContext = Depends(get_app_context)
):
    try:
        catalog_entries = await catalog_service.fetch_all_entries(context)
        return templates.TemplateResponse("catalog.html", {
            "request": request,
            "catalog_entries": catalog_entries
        })
    except Exception as e:
        logger.error(f"Error displaying the catalog page: {e}")
        return HTMLResponse("<p>Error loading the catalog page. Please try again later.</p>", status_code=500)

@router.post("/upload", response_class=HTMLResponse)
async def upload_playbook(
    request: Request,
    playbook_file: UploadFile = File(...),
    catalog_service: CatalogService = Depends(get_catalog_service),
    context: AppContext = Depends(get_app_context)
):
    try:
        logger.info(f"Upload request file: {playbook_file.filename}")
        raw_content = await playbook_file.read()
        base64_content = base64.b64encode(raw_content).decode("utf-8")
        response = await catalog_service.register_entry(
            content_base64=base64_content,
            event_type="REGISTERED",
            context=context
        )
        catalog_entries = await catalog_service.fetch_all_entries(context)
        return templates.TemplateResponse("catalog.html", {
            "request": request,
            "catalog_entries": catalog_entries,
            "message": response.get("message", "")
        })
    except Exception as e:
        logger.error(f"Error uploading playbook: {e}")
        return HTMLResponse(f"<p>Error processing the uploaded file: {e}</p>", status_code=500)

@router.get("/editor", response_class=HTMLResponse)
async def editor(
    request: Request,
    type: str,
    resource_path: str,
    resource_version: str,
    catalog_service: CatalogService = Depends(get_catalog_service),
    context: AppContext = Depends(get_app_context)
):
    try:
        entry = await catalog_service.fetch_entry_path_version(
            context, resource_path, resource_version
        )
        if not entry:
            raise HTTPException(
                status_code=404,
                detail=f"Catalog entry for '{resource_path}' with version '{resource_version}' not found."
            )
        if type == "content":
            data = entry["content"]
            language = "yaml"
        elif type == "payload":
            data = json.dumps(entry["payload"], indent=2)
            language = "json"
        else:
            raise HTTPException(status_code=400, detail="Invalid type. Must be 'content' or 'payload'.")

        return templates.TemplateResponse("editor.html", {
            "request": request,
            "type": type,
            "resource_path": resource_path,
            "resource_version": resource_version,
            "data": data,
            "language": language
        })
    except Exception as e:
        logger.error(f"Error opening editor: {e}")
        return HTMLResponse(f"<p>Error opening editor for '{resource_path}' (version '{resource_version}'): {e}</p>", status_code=500)

from deepdiff import DeepDiff

@router.post("/save", response_class=RedirectResponse)
async def save_editor(
    resource_path: str = Form(...),
    resource_version: str = Form(...),
    type: str = Form(...),
    data: str = Form(...),
    catalog_service: CatalogService = Depends(get_catalog_service),
    context: AppContext = Depends(get_app_context)
):
    try:
        logger.info(f"Attempting to save {type} for resource_path='{resource_path}' (version='{resource_version}').")
        async with context.postgres.get_session() as session:
            current_entry = await catalog_service.fetch_entry_path_version(
                context, resource_path, resource_version
            )

        if not current_entry:
            raise HTTPException(
                status_code=404,
                detail=f"No matching entry found for '{resource_path}' version '{resource_version}'."
            )

        existing_content = current_entry["content"].strip()
        existing_payload = current_entry["payload"]

        if type == "content":
            new_content = data.strip()
            try:
                new_payload = yaml.safe_load(new_content)
            except yaml.YAMLError as e:
                raise HTTPException(status_code=400, detail=f"Invalid YAML format: {e}")
        elif type == "payload":
            try:
                new_payload = json.loads(data)
                new_content = yaml.dump(new_payload, default_flow_style=False).strip()
            except json.JSONDecodeError as e:
                raise HTTPException(status_code=400, detail=f"Invalid JSON format: {e}")
        else:
            raise HTTPException(status_code=400, detail="Invalid type. Must be 'content' or 'payload'.")

        existing_content_normalized = yaml.dump(yaml.safe_load(existing_content), default_flow_style=False).strip()
        new_content_normalized = yaml.dump(yaml.safe_load(new_content), default_flow_style=False).strip()

        if existing_content_normalized == new_content_normalized and DeepDiff(existing_payload, new_payload) == {}:
            logger.info(f"No changes detected for '{resource_path}' (version='{resource_version}').")
            return RedirectResponse(url="/", status_code=303)

        updated_entry = await create_catalog_entry(session, new_content_normalized, new_payload, resource_version)
        logger.info(f"Saved new version '{updated_entry.resource_version}' for '{resource_path}'.")

        return RedirectResponse(url="/", status_code=303)

    except Exception as e:
        logger.error(f"Error saving {type} for {resource_path} (version={resource_version}): {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error saving {type} for '{resource_path}' (version '{resource_version}'): {e}"
        )
