from noetl.server.api.catalog.schema import (
    CatalogEntry,
    CatalogEntryRequest,
    CatalogEntriesRequest,
    CatalogEntries,
    transform,
)
from .service import CatalogService, get_catalog_service
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import JSONResponse
import json
import yaml
from noetl.core.common import (
    get_async_db_connection,
)
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)
router = APIRouter()


@router.post("/catalog/register", response_class=JSONResponse, tags=["Catalog"])
async def register_resource(
    request: Request,
    catalog_service: CatalogService = Depends(get_catalog_service),
    content_base64: str = None,
    content: str = None,
    resource_type: str = "Playbook"
):
    try:
        if not content_base64 and not content:
            try:
                body = await request.json()
                content_base64 = body.get("content_base64")
                content = body.get("content")
                resource_type = body.get("resource_type", resource_type)
            except:
                pass

        if content_base64:
            import base64 as _b64
            content = _b64.b64decode(content_base64).decode('utf-8')
        elif not content:
            raise HTTPException(
                status_code=400,
                detail="The content or content_base64 must be provided."
            )

        result = await catalog_service.register_resource(content, resource_type)
        return result

    except Exception as e:
        logger.exception(f"Error registering resource: {e}.")
        raise HTTPException(
            status_code=500,
            detail=f"Error registering resource: {e}."
        )


@router.post(
    "/catalog/list",
    response_model=CatalogEntries,
    tags=["Catalog"],
    summary="List all catalog resources",
    description="""
Retrieve a list of all catalog entries, optionally filtered by resource type.

**Request Body:**
- `resource_type` (optional): Filter by resource kind (e.g., "Playbook", "Tool", "Model")

**Returns:**
- List of catalog entries ordered by creation date (newest first)
- Each entry includes: path, kind, version, content, layout, payload, meta, created_at

**Examples:**

Get all resources:
```json
POST /catalog/list
{}
```

Get only Playbooks:
```json
POST /catalog/list
{
  "resource_type": "Playbook"
}
```

**Response:**
```json
{
  "entries": [
    {
      "path": "examples/hello_world",
      "kind": "Playbook",
      "version": 2,
      "content": "apiVersion: noetl.io/v1...",
      "payload": {...},
      "meta": {...},
      "created_at": "2025-10-24T12:00:00Z"
    }
  ]
}
```
    """
)
async def list_resources(
    request: Request,
    payload: CatalogEntriesRequest,
    catalog_service: CatalogService = Depends(get_catalog_service)
):
    try:
        return await catalog_service.fetch_entries(payload.resource_type)
        # Convert CatalogResourceRequest Pydantic models to response models
        # return {
        #     "entries": [
        #         CatalogResourceResponse(
        #             catalog_id=entry.catalog_id,
        #             path=entry.path,
        #             kind=entry.kind,
        #             version=entry.version,
        #             content=entry.content,
        #             layout=entry.layout,
        #             payload=entry.payload,
        #             meta=entry.meta,
        #             created_at=entry.created_at
        #         )
        #         for entry in entries
        #     ]
        # }

    except Exception as e:
        logger.exception(f"Error listing resources: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error listing resources: {e}"
        )


@router.post(
    "/catalog/resource",
    response_model=CatalogEntry,
    tags=["Catalog"],
    summary="Get catalog resource versions",
    description="""
Retrieve catalog resource(s) using unified lookup strategies.

**Supported Lookup Strategies** (priority order):
1. `catalog_id`: Direct catalog entry lookup (highest priority)
2. `path` + `version`: Version-controlled path-based lookup

**Request Body:**
- **Identifiers** (at least one required):
  - `catalog_id`: Direct catalog entry ID
  - `path`: Catalog path for resource
  - `version`: Version identifier (default: "latest")

**Returns:**
- Single resource if `catalog_id` or `path`+`version` specified
- Latest version if only `path` specified
- Each entry includes: path, kind, version, content, layout, payload, meta, created_at

**Examples:**

Get specific version by catalog_id:
```json
POST /catalog/resource
{
  "catalog_id": "123456789"
}
```

Get specific version by path and version:
```json
POST /catalog/resource
{
  "path": "examples/hello_world",
  "version": 2
}
```

Get latest version:
```json
POST /catalog/resource
{
  "path": "examples/hello_world",
  "version": "latest"
}
```

Get all versions of a resource:
```json
POST /catalog/resource
{
  "path": "examples/hello_world"
}
```

**Response:**
```json
[
  {
    "path": "examples/hello_world",
    "kind": "Playbook",
    "version": 2,
    "content": "apiVersion: noetl.io/v1...",
    "payload": {...},
    "meta": {...},
    "created_at": "2025-10-24T12:00:00Z"
  }
]
```
    """
)
async def get_catalog_entry(
    payload: CatalogEntryRequest,
    catalog_service: CatalogService = Depends(get_catalog_service)
):
    """Get catalog resource(s) using unified lookup strategies"""
    result = await catalog_service.get(
        path=payload.path, 
        version=payload.version, 
        catalog_id=payload.catalog_id
    )
    # Return single entry or raise 404
    if not result:
        raise HTTPException(status_code=404, detail="Catalog entry not found")
    return result
    # try:
    #     # Determine lookup strategy
    #     # Priority: catalog_id > path+version > path only
        
    #     # If catalog_id is provided or path+version (not "latest"), fetch single resource
    #     if payload.catalog_id or (payload.path and payload.version and payload.version != "latest"):
    #         resource_version = payload.version if payload.version != "latest" else None
    #         entry = await CatalogService._get_resource(
    #             catalog_id=payload.catalog_id,
    #             path=payload.path,
    #             version=resource_version
    #         )
    #         if not entry:
    #             identifier = payload.catalog_id or f"{payload.path}@{payload.version}"
    #             raise HTTPException(
    #                 status_code=404,
    #                 detail=f"Resource '{identifier}' not found"
    #             )
    #         return [
    #             CatalogResourceResponse(
    #                 catalog_id=entry.catalog_id,
    #                 path=entry.path,
    #                 kind=entry.kind,
    #                 version=entry.version,
    #                 content=entry.content,
    #                 layout=entry.layout,
    #                 payload=entry.payload,
    #                 meta=entry.meta or {},
    #                 created_at=entry.created_at
    #             )
    #         ]
        
    #     # If path + "latest", fetch latest version
    #     if payload.path and payload.version == "latest":
    #         entry = await CatalogService._get_resource(
    #             path=payload.path,
    #             version="latest"
    #         )
    #         if not entry:
    #             raise HTTPException(
    #                 status_code=404,
    #                 detail=f"Resource '{payload.path}' not found"
    #             )
    #         return [
    #             CatalogResourceResponse(
    #                 catalog_id=entry.catalog_id,
    #                 path=entry.path,
    #                 kind=entry.kind,
    #                 version=entry.version,
    #                 content=entry.content,
    #                 layout=entry.layout,
    #                 payload=entry.payload,
    #                 meta=entry.meta or {},
    #                 created_at=entry.created_at
    #             )
    #         ]
        
    #     # If only path (no version or version is None), fetch all versions
    #     if payload.path:
    #         entries = await catalog_service.entry_all_versions(payload.path)
    #         if not entries:
    #             raise HTTPException(
    #                 status_code=404,
    #                 detail=f"No resources found for path '{payload.path}'"
    #             )
    #         return [
    #             CatalogResourceResponse(
    #                 catalog_id=entry.catalog_id,
    #                 path=entry.path,
    #                 kind=entry.kind,
    #                 version=entry.version,
    #                 content=entry.content,
    #                 layout=entry.layout,
    #                 payload=entry.payload,
    #                 meta=entry.meta or {},
    #                 created_at=entry.created_at
    #             )
    #             for entry in entries
    #         ]
        
    #     raise HTTPException(
    #         status_code=400,
    #         detail="Invalid request: provide catalog_id or path"
    #     )
        
    # except HTTPException:
    #     raise
    # except Exception as e:
    #     logger.error(f"Error getting resource: {e}")
    #     raise HTTPException(status_code=500, detail=str(e))


# @router.get("/catalog/playbook/content", response_class=JSONResponse, tags=["Catalog"])
# async def get_catalog_playbook_content(
#     playbook_id: str,
#     request: Request,
#     catalog_service: CatalogService = Depends(get_catalog_service_dependency),
#     version: Optional[str] = None
# ):
#     """Get playbook raw content"""
#     try:
#         logger.info(f"Received playbook_id for content: '{playbook_id}'")
#         # Accept any path structure - no prefix validation required
#         body = None
#         try:
#             body = await request.json()
#         except Exception:
#             pass
#         if not version and isinstance(body, dict):
#             version = body.get('version')
#         if not version:
#             version = await catalog_service.get_latest_version(playbook_id)
#         entry = await catalog_service.fetch_entry(playbook_id, version)
#         if not entry:
#             raise HTTPException(
#                 status_code=404, detail=f"Playbook '{playbook_id}' with version '{version}' not found.")

#         return {
#             "path": playbook_id,
#             "version": version,
#             "content": entry.content
#         }
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error getting playbook content: {e}")
#         raise HTTPException(status_code=500, detail=str(e))

# @router.get("/catalog/playbook", response_class=JSONResponse, tags=["Catalog"])
# async def get_catalog_playbook(
#     playbook_id: str,
#     catalog_service: CatalogService = Depends(get_catalog_service_dependency),
#     version: Optional[str] = None
# ):
#     """Get playbook by ID, optionally by version"""
#     try:
#         logger.info(f"Received playbook_id: '{playbook_id}'")
#         # Accept any path structure - no prefix validation required

#         if not version:
#             version = await catalog_service.get_latest_version(playbook_id)

#         entry = await catalog_service.fetch_entry(playbook_id, version)
#         if not entry:
#             raise HTTPException(
#                 status_code=404, detail=f"Playbook '{playbook_id}' with version '{version}' not found.")

#         try:
#             content = entry.content or ''
#             if isinstance(content, bytes):
#                 content = content.decode('utf-8', errors='ignore')
#             payload = yaml.safe_load(content) or {}
#         except Exception:
#             payload = {}

#         # Convert CatalogResourceRequest to dict for JSON response
#         return {
#             "catalog_id": entry.catalog_id,
#             "path": entry.path,
#             "version": entry.version,
#             "kind": entry.kind,
#             "content": entry.content,
#             "layout": entry.layout,
#             "payload": payload,
#             "meta": entry.meta,
#             "created_at": entry.created_at,
#         }
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error getting playbook: {e}")
#         raise HTTPException(status_code=500, detail=str(e))

# @router.put("/catalog/playbook/content", response_class=JSONResponse, tags=["Catalog"])
# async def save_catalog_playbook_content(
#     playbook_id: str,
#     request: Request,
#     catalog_service: CatalogService = Depends(get_catalog_service_dependency)
# ):
#     """Save playbook content (stores new version)."""
#     try:
#         logger.info(f"Received playbook_id for save: '{playbook_id}'")
#         # Accept any path structure - no prefix validation required
#         body = await request.json()
#         content = body.get("content")
#         if not content:
#             raise HTTPException(status_code=400, detail="Content is required.")
#         # Normalize YAML so resource_path matches URL id
#         try:
#             parsed = yaml.safe_load(content) or {}
#             if isinstance(parsed, dict):
#                 if 'metadata' in parsed and isinstance(parsed['metadata'], dict):
#                     parsed['metadata']['path'] = playbook_id
#                     parsed['metadata'].setdefault(
#                         'name', playbook_id.split('/')[-1])
#                 else:
#                     meta = parsed.get('metadata') if isinstance(
#                         parsed.get('metadata'), dict) else {}
#                     meta['path'] = playbook_id
#                     meta.setdefault('name', playbook_id.split('/')[-1])
#                     parsed['metadata'] = meta
#                 parsed['path'] = playbook_id
#                 parsed.setdefault('name', playbook_id.split('/')[-1])
#                 content = yaml.safe_dump(parsed, sort_keys=False)
#         except Exception as norm_err:
#             logger.warning(
#                 f"Failed to normalize playbook path in YAML: {norm_err}")
#         # Use consistent resource type capitalization
#         result = await catalog_service.register_resource(content, "Playbook")
#         return {"status": "success", "message": f"Playbook '{playbook_id}' content updated.", "path": result.get("path"), "version": result.get("version")}
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error saving playbooks content: {e}")
#         raise HTTPException(status_code=500, detail=str(e))


# @router.get("/catalog/playbook/fallback", response_class=JSONResponse, tags=["Catalog"])
# async def get_catalog_playbook_fallback(
#     playbook_id: str,
#     catalog_service: CatalogService = Depends(get_catalog_service_dependency),
#     version: Optional[str] = None
# ):
#     """Get playbook by ID, optionally by version

#     Fallback: if a request meant for the /content endpoint is misrouted here (because of
#     path matching order or stale server code) we detect the trailing '/content' segment
#     and internally serve the raw content response to avoid a 404 like:
#       Playbook '.../content' with version 'x.y.z' not found.
#     """
#     try:
#         logger.info(f"Received playbook_id: '{playbook_id}'")
#         # Accept any path structure - no prefix validation required

#         # Fallback handling for misrouted content requests
#         if playbook_id.endswith("/content") or playbook_id.endswith("/content/"):
#             original_id = playbook_id.rstrip('/').rsplit('/content', 1)[0]
#             logger.warning(
#                 "Misrouted playbook content request detected for '%s'; serving content via fallback.",
#                 original_id
#             )
#             if not version:
#                 version = await catalog_service.get_latest_version(original_id)
#             entry = await catalog_service.fetch_entry(original_id, version)
#             if not entry:
#                 raise HTTPException(
#                     status_code=404, detail=f"Playbook '{original_id}' with version '{version}' not found.")
#             return {"path": original_id, "version": version, "content": entry.content}

#         if not version:
#             version = await catalog_service.get_latest_version(playbook_id)
#         entry = await catalog_service.fetch_entry(playbook_id, version)
#         if not entry:
#             raise HTTPException(
#                 status_code=404, detail=f"Playbook '{playbook_id}' with version '{version}' not found.")
        
#         try:
#             content = entry.content or ''
#             if isinstance(content, bytes):
#                 content = content.decode('utf-8', errors='ignore')
#             payload = yaml.safe_load(content) or {}
#         except Exception:
#             payload = {}
        
#         # Convert CatalogResourceRequest to dict for JSON response
#         return {
#             "catalog_id": entry.catalog_id,
#             "path": entry.path,
#             "version": entry.version,
#             "kind": entry.kind,
#             "content": entry.content,
#             "layout": entry.layout,
#             "payload": payload,
#             "meta": entry.meta,
#             "created_at": entry.created_at,
#         }
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error getting playbook: {e}")
#         raise HTTPException(status_code=500, detail=str(e))


# @router.get("/catalog/widgets", response_class=JSONResponse, tags=["Catalog"])
# async def get_catalog_widgets():
#     """Get catalog visualization widgets"""
#     try:
#         playbook_count = 0
#         active_count = 0
#         draft_count = 0

#         try:
#             async with get_async_db_connection() as conn:
#                 async with conn.cursor() as cursor:
#                     await cursor.execute(
#                         "SELECT COUNT(DISTINCT path) FROM noetl.catalog WHERE kind = 'Playbook'"
#                     )
#                     row = await cursor.fetchone()
#                     playbook_count = row[0] if row else 0

#                     await cursor.execute(
#                         """
#  SELECT meta FROM noetl.catalog
#  WHERE kind = 'Playbook'
#                         """
#                     )
#                     results = await cursor.fetchall()

#                     for row in results:
#                         meta_str = row[0]
#                         if meta_str:
#                             try:
#                                 meta = json.loads(meta_str) if isinstance(
#                                     meta_str, str) else meta_str
#                                 status = meta.get('status', 'active')
#                                 if status == 'active':
#                                     active_count += 1
#                                 elif status == 'draft':
#                                     draft_count += 1
#                             except (json.JSONDecodeError, TypeError):
#                                 active_count += 1
#                         else:
#                             active_count += 1
#         except Exception as db_error:
#             logger.warning(
#                 f"Error getting catalog stats from database: {db_error}")
#             playbook_count = 0

#         return [
#             {
#                 "id": "catalog-summary",
#                 "type": "metric",
#                 "title": "Total Playbooks",
#                 "data": {
#                     "value": playbook_count
#                 },
#                 "config": {
#                     "format": "number",
#                     "color": "#1890ff"
#                 }
#             },
#             {
#                 "id": "active-playbooks",
#                 "type": "metric",
#                 "title": "Active Playbooks",
#                 "data": {
#                     "value": active_count
#                 },
#                 "config": {
#                     "format": "number",
#                     "color": "#52c41a"
#                 }
#             },
#             {
#                 "id": "draft-playbooks",
#                 "type": "metric",
#                 "title": "Draft Playbooks",
#                 "data": {
#                     "value": draft_count
#                 },
#                 "config": {
#                     "format": "number",
#                     "color": "#faad14"
#                 }
#             }
#         ]
#     except Exception as e:
#         logger.error(f"Error getting catalog widgets: {e}")
#         raise HTTPException(status_code=500, detail=str(e))


# # Dependency/helper for runtime to get playbook entry


# async def get_playbook_entry_from_catalog(playbook_id: str) -> Dict[str, Any]:
#     logger.info(f"Dependency received playbook_id: '{playbook_id}'")
#     path_to_lookup = playbook_id.replace('%2F', '/')
#     # Accept any path structure - no prefix validation required
#     version_to_lookup = None
#     if ':' in path_to_lookup:
#         path_parts = path_to_lookup.rsplit(':', 1)
#         if path_parts[1].replace('.', '').isdigit():
#             path_to_lookup = path_parts[0]
#             logger.info(
#                 f"Parsed and cleaned path to '{path_to_lookup}' from malformed ID.")

#     catalog_service = get_catalog_service()
#     latest_version = await catalog_service.get_latest_version(path_to_lookup)
#     logger.info(
#         f"Using latest version for '{path_to_lookup}': {latest_version}")

#     entry = await catalog_service.fetch_entry(path_to_lookup, latest_version)
#     if not entry:
#         raise HTTPException(
#             status_code=404,
#             detail=f"Playbook '{path_to_lookup}' with version '{latest_version}' not found in catalog."
#         )
    
#     # Convert CatalogResourceRequest to dict for backwards compatibility
#     return {
#         "catalog_id": entry.catalog_id,
#         "path": entry.path,
#         "version": entry.version,
#         "kind": entry.kind,
#         "content": entry.content,
#         "layout": entry.layout,
#         "payload": entry.payload,
#         "meta": entry.meta,
#         "created_at": entry.created_at,
#     }
