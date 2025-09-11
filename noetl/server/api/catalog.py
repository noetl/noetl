from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse
import base64

from noetl.server.services import (
    CatalogService,
    get_catalog_service_dependency,
    get_playbook_entry_from_catalog,
)

router = APIRouter()


@router.post("/catalog/register", response_class=JSONResponse)
async def register_resource(request: Request, content_base64: str | None = None, content: str | None = None, resource_type: str = "Playbook"):
    # If provided as query/form param, decode first
    if content_base64 and not content:
        try:
            content = base64.b64decode(content_base64).decode("utf-8")
        except Exception as e:
            return JSONResponse(content={"error": f"Invalid base64 content: {e}"}, status_code=400)

    # If still no content, try JSON body and support both 'content' and 'content_base64' keys
    if not content:
        json_body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else None
        if json_body:
            # resource_type may be provided in JSON
            resource_type = json_body.get("resource_type", resource_type)
            body_content = json_body.get("content")
            body_b64 = json_body.get("content_base64")
            if body_content:
                content = body_content
            elif body_b64:
                try:
                    content = base64.b64decode(body_b64).decode("utf-8")
                except Exception as e:
                    return JSONResponse(content={"error": f"Invalid base64 content: {e}"}, status_code=400)
        if not content:
            return JSONResponse(content={"error": "content is required"}, status_code=400)

    svc = CatalogService()
    result = svc.register_resource(content=content, resource_type=resource_type)
    return JSONResponse(content=result)


@router.get("/catalog/list", response_class=JSONResponse)
async def list_resources(request: Request, resource_type: str | None = None):
    svc = CatalogService()
    entries = svc.list_entries(resource_type=resource_type)
    return JSONResponse(content=entries)


@router.get("/catalog/{path:path}/{version}", response_class=JSONResponse)
async def get_resource(request: Request, path: str, version: str):
    svc = CatalogService()
    result = svc.fetch_entry(path, version)
    return JSONResponse(content=result or {"error": "Not found"}, status_code=200 if result else 404)


@router.get("/playbooks", response_class=JSONResponse)
async def get_playbooks():
    # Placeholder for compatibility
    return JSONResponse(content={"status": "ok"})


@router.get("/catalog/playbooks", response_class=JSONResponse)
async def get_catalog_playbooks():
    svc = CatalogService()
    entries = svc.list_entries(resource_type="Playbook")
    return JSONResponse(content=entries)


@router.post("/catalog/playbooks", response_class=JSONResponse)
async def create_catalog_playbook(request: Request):
    body = await request.json()
    content = body.get("content")
    if not content:
        return JSONResponse(content={"error": "content is required"}, status_code=400)
    svc = CatalogService()
    result = svc.register_resource(content=content, resource_type="Playbook")
    return JSONResponse(content=result)


@router.post("/catalog/playbooks/validate", response_class=JSONResponse)
async def validate_catalog_playbook(request: Request):
    body = await request.json()
    content = body.get("content")
    if not content:
        return JSONResponse(content={"error": "content is required"}, status_code=400)
    # For now just parse as YAML to validate
    try:
        import yaml
        yaml.safe_load(content)
        return JSONResponse(content={"status": "valid"})
    except Exception as e:
        return JSONResponse(content={"status": "invalid", "error": str(e)})


@router.post("/executions/run", response_class=JSONResponse)
async def execute_playbook(request: Request):
    body = await request.json()
    playbook_id = body.get("playbook_id")
    version = body.get("version")
    input_payload = body.get("input_payload", {})

    entry = get_playbook_entry_from_catalog(playbook_id)
    if not entry:
        return JSONResponse(content={"error": "Playbook not found"}, status_code=404)
    # Placeholder execution path: return the input
    return JSONResponse(content={"status": "scheduled", "playbook_id": playbook_id, "version": version, "input": input_payload})


@router.get("/catalog/playbooks/content", response_class=JSONResponse)
async def get_catalog_playbook_content(playbook_id: str = Query(...), version: Optional[str] = Query(default=None)):
    entry = get_playbook_entry_from_catalog(playbook_id)
    if not entry:
        return JSONResponse(content={"error": "Not found"}, status_code=404)
    return JSONResponse(content=entry)


@router.get("/catalog/playbook", response_class=JSONResponse)
async def get_catalog_playbook(playbook_id: str = Query(...)):
    entry = get_playbook_entry_from_catalog(playbook_id)
    if not entry:
        return JSONResponse(content={"error": "Not found"}, status_code=404)
    return JSONResponse(content=entry)


@router.put("/catalog/playbooks/{playbook_id:path}/content", response_class=JSONResponse)
async def save_catalog_playbook_content(playbook_id: str, request: Request):
    body = await request.json()
    content = body.get("content")
    if not content:
        return JSONResponse(content={"error": "content is required"}, status_code=400)
    svc = CatalogService()
    result = svc.register_resource(content=content, resource_type="Playbook")
    result["resource_path"] = playbook_id
    return JSONResponse(content=result)
