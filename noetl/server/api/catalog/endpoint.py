from noetl.server.api.catalog.schema import (
    CatalogEntry,
    CatalogEntryRequest,
    CatalogEntriesRequest,
    CatalogEntries,
    CatalogRegisterRequest,
    CatalogRegisterResponse,
)
from .service import CatalogService, get_catalog_service
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import JSONResponse
from noetl.core.logger import setup_logger
import base64

logger = setup_logger(__name__, include_location=True)
router = APIRouter()


@router.post(
    "/catalog/register",
    response_model=CatalogRegisterResponse,
    tags=["Catalog"],
    summary="Register a new catalog resource",
    description="""
Register a new catalog resource (Playbook, Tool, Model, etc.) with version control.

**Request Body:**
- `content`: YAML content of the resource (accepts base64 encoded or plain text)
- `resource_type`: Type of resource to register (default: "Playbook")

**Behavior:**
- Automatically increments version if resource already exists at the same path
- Extracts metadata (name, path, kind) from YAML content
- Validates resource structure before registration

**Returns:**
- Registration confirmation with catalog_id, path, version, and kind

**Examples:**

Register a new Playbook:
```json
POST /catalog/register
{
  "content": "apiVersion: noetl.io/v1\\nkind: Playbook\\nmetadata:\\n  name: example\\n  path: tests/fixtures/playbooks/hello_world/hello_world\\n...",
  "resource_type": "Playbook"
}
```

Register with base64 encoded content:
```json
POST /catalog/register
{
  "content": "YXBpVmVyc2lvbjogbm9ldGwuaW8vdjEKa2luZDogUGxheWJvb2s=",
  "resource_type": "Playbook"
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Resource 'tests/fixtures/playbooks/hello_world/hello_world' version '1' registered.",
  "path": "tests/fixtures/playbooks/hello_world/hello_world",
  "version": 1,
  "catalog_id": "478775660589088776",
  "kind": "Playbook"
}
```
    """
)
async def register_resource(
    request: CatalogRegisterRequest,
    catalog_service: CatalogService = Depends(get_catalog_service),
):
    try:
        result = await catalog_service.register_resource(request.content, request.resource_type)
        return CatalogRegisterResponse(**result)
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
      "path": "tests/fixtures/playbooks/hello_world/hello_world",
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
  "path": "tests/fixtures/playbooks/hello_world/hello_world",
  "version": 2
}
```

Get latest version:
```json
POST /catalog/resource
{
  "path": "tests/fixtures/playbooks/hello_world/hello_world",
  "version": "latest"
}
```

Get all versions of a resource:
```json
POST /catalog/resource
{
  "path": "tests/fixtures/playbooks/hello_world/hello_world"
}
```

**Response:**
```json
[
  {
    "path": "tests/fixtures/playbooks/hello_world/hello_world",
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
