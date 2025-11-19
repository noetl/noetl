from noetl.server.api.catalog.schema import (
    CatalogEntry,
    CatalogEntryRequest,
    CatalogEntriesRequest,
    CatalogEntries,
)
from .service import CatalogService, get_catalog_service
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import JSONResponse
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
