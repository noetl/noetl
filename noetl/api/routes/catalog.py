from datetime import datetime
from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates


from noetl.api.schemas.catalog import RegisterRequest
from noetl.api.services.catalog import CatalogService
import base64
import json
import yaml
from noetl.util.serialization import ordered_yaml_dump, ordered_yaml_load
from deepdiff import DeepDiff
from noetl.config.settings import AppConfig
from noetl.connectors.hub import get_connector_hub, ConnectorHub
from noetl.util import setup_logger
logger = setup_logger(__name__, include_location=True)
app_config = AppConfig()
templates = Jinja2Templates(directory=app_config.get_template_folder("catalog"))
# TODO need centralize templates initialization
def datetimeformat(value, format='%Y-%m-%d %H:%M'):
    if isinstance(value, str):
        value = datetime.strptime(value, '%Y-%m-%d %H:%M:%S.%f')
    return value.strftime(format)

templates.env.filters['datetimeformat'] = datetimeformat

router = APIRouter(prefix="/catalog")

def get_catalog_service(context: ConnectorHub = Depends(get_connector_hub)) -> CatalogService:
    return CatalogService(context)

@router.post("/register")
async def register_resource(
    request_data: RegisterRequest,
    catalog_service: CatalogService = Depends(get_catalog_service)
):
    content_base64 = request_data.content_base64
    logger.info("Received request to register resource.", extra={"content_base64": content_base64})
    return await catalog_service.register_entry(
        content_base64=content_base64,
        state="REQUESTED"
    )

@router.get("/", response_class=HTMLResponse)
async def catalog_page(
    request: Request,
    catalog_service: CatalogService = Depends(get_catalog_service)
):
    try:
        catalog_entries = await catalog_service.fetch_all_entries()
        return templates.TemplateResponse("catalog_page.html", {
            "request": request,
            "catalog_entries": catalog_entries
        })
    except Exception as e:
        logger.error(f"Catalog page error: {e}")
        return HTMLResponse("<p>Error loading the catalog page.</p>", status_code=500)

@router.post("/upload", response_class=JSONResponse)
async def upload_playbook(
    request: Request,
    playbook_file: UploadFile = File(...),
    catalog_service: CatalogService = Depends(get_catalog_service)
):
    try:
        logger.info(f"Upload request file: {playbook_file.filename}")
        raw_content = await playbook_file.read()
        base64_content = base64.b64encode(raw_content).decode("utf-8")
        response = await catalog_service.register_entry(
            content_base64=base64_content,
            state="REQUESTED"
        )
        message = response.get("message", "")
        catalog_entries = await catalog_service.fetch_all_entries()
        catalog_table_html = templates.get_template("catalog_table.html").render({
            "catalog_entries": catalog_entries,
            "request": request,
        })

        status_html = templates.get_template("status.html").render({
            "message": message,
            "request": request,
        })

        return JSONResponse({
            "table_html": catalog_table_html,
            "status_html": status_html
        })

    except Exception as e:
        logger.exception(f"Error uploading playbook: {e}")
        return JSONResponse({
            "table_html": "",
            "status_html": f"<p><strong>Error:</strong> {str(e)}</p>"
        }, status_code=500)


@router.get("/editor", response_class=HTMLResponse)
async def editor(
    request: Request,
    type: str,
    resource_path: str,
    resource_version: str,
    catalog_service: CatalogService = Depends(get_catalog_service)
):
    try:
        entry = await catalog_service.fetch_entry(resource_path, resource_version)
        if not entry:
            raise HTTPException(
                status_code=404,
                detail=f"Catalog entry for '{resource_path}' with version '{resource_version}' not found."
            )
        if type == "content":
            data = entry.get("content")
            language = "yaml"
        elif type == "payload":
            data = json.dumps(entry.get("payload"), indent=2)
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

@router.post("/save", response_class=RedirectResponse)
async def save_editor(
    resource_path: str = Form(...),
    resource_version: str = Form(...),
    type: str = Form(...),
    data: str = Form(...),
    catalog_service: CatalogService = Depends(get_catalog_service)
):
    try:
        logger.info(f"Saving {type} for resource_path='{resource_path}' (version='{resource_version}').")
        current_entry = await catalog_service.fetch_entry(resource_path, resource_version)

        if not current_entry:
            raise HTTPException(
                status_code=404,
                detail=f"No matching entry found for '{resource_path}' version '{resource_version}'."
            )

        content = current_entry.get("content").strip()
        payload = current_entry.get("payload")

        result = compare_content(
            type=type,
            data=data,
            content=content,
            payload=payload,
            resource_path=resource_path,
            resource_version=resource_version
        )

        if result is None:
            return RedirectResponse(url="/", status_code=303)

        new_content, new_payload = result
        updated_entry = await catalog_service.create_catalog_entry(new_content, new_payload)
        logger.info(f"Saved new version '{updated_entry.resource_version}' for '{resource_path}'.")

        return RedirectResponse(url="/", status_code=303)
    except Exception as e:
        logger.error(f"Error saving {type} for {resource_path} (version={resource_version}): {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error saving {type} for '{resource_path}' (version '{resource_version}'): {e}"
        )

def parse_editor_data(type: str, data: str) -> tuple[str, dict]:
    if type == "content":
        new_content = data.strip()
        try:
            new_payload = yaml.safe_load(new_content)
            return new_content, new_payload
        except yaml.YAMLError as e:
            raise HTTPException(status_code=400, detail=f"Invalid YAML format: {e}")
    elif type == "payload":
        try:
            new_payload = json.loads(data)
            new_content = ordered_yaml_dump(new_payload).strip()
            return new_content, new_payload
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON format: {e}")
    else:
        raise HTTPException(status_code=400, detail="Invalid type. Must be 'content' or 'payload'.")

def compare_content(
    type: str,
    data: str,
    content: str,
    payload: dict,
    resource_path: str,
    resource_version: str
):
    new_content, new_payload = parse_editor_data(type, data)
    new_content_striped = ordered_yaml_dump(ordered_yaml_load(new_content)).strip()
    payload_diff = DeepDiff(payload, new_payload, ignore_order=True)
    if ordered_yaml_dump( ordered_yaml_load(content)).strip() == new_content_striped and not payload_diff:
        logger.info(f"No changes detected for '{resource_path}' (version='{resource_version}').")
        return None
    return new_content_striped, new_payload
