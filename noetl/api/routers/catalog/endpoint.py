from noetl.api.routers.catalog.schemas.catalog_resource import PlaybookResourceResponse, transform
from .service import CatalogService, get_catalog_service
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, Request, Query, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
import base64
import json
import yaml
from datetime import datetime
from psycopg.types.json import Json
from psycopg.rows import dict_row
from noetl.core.common import (
    deep_merge,
    get_pgdb_connection,
    get_async_db_connection,
    get_snowflake_id_str,
    get_snowflake_id,
)
from noetl.core.logger import setup_logger
from .service import get_catalog_service

logger = setup_logger(__name__, include_location=True)
router = APIRouter()


@router.post("/catalog/register", response_class=JSONResponse)
async def register_resource(
    request: Request,
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

        catalog_service = get_catalog_service()
        result = await catalog_service.register_resource(content, resource_type)
        return result

    except Exception as e:
        logger.exception(f"Error registering resource: {e}.")
        raise HTTPException(
            status_code=500,
            detail=f"Error registering resource: {e}."
        )


@router.get("/catalog/list", response_class=JSONResponse)
async def list_resources(
    request: Request,
    resource_type: str = None
):
    try:
        catalog_service = get_catalog_service()
        entries = await catalog_service.list_entries(resource_type)
        return {"entries": entries}

    except Exception as e:
        logger.exception(f"Error listing resources: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error listing resources: {e}"
        )


@router.get("/playbooks", response_class=JSONResponse)
async def get_playbooks():
    """Get all playbooks (legacy endpoint)"""
    return await get_catalog_playbooks()


@router.get(
    "/catalog/resource",
    response_model=list[PlaybookResourceResponse],
    tags=["Catalog"],
)
async def get_catalog_resource(resource_path: str):
    """Get resource by path all versions"""
    try:
        from .service import get_catalog_service
        catalog_service = get_catalog_service()
        entries = await catalog_service.entry_all_versions(resource_path)
        return [transform(PlaybookResourceResponse, entry) for entry in entries]
    except Exception as e:
        logger.error(f"Error getting playbooks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog/playbooks", response_class=JSONResponse)
async def get_catalog_playbooks():
    """Get all playbooks"""
    try:
        from .service import get_catalog_service
        catalog_service = get_catalog_service()
        entries = await catalog_service.list_entries('Playbook')

        playbooks = []
        for entry in entries:
            meta = entry.get('meta', {})

            description = ""
            payload = entry.get('payload', {})

            if isinstance(payload, str):
                try:
                    payload_data = json.loads(payload)
                    description = payload_data.get('description', '')
                except json.JSONDecodeError:
                    description = ""
            elif isinstance(payload, dict):
                description = payload.get('description', '')

            if not description:
                description = meta.get('description', '')

            playbook = {
                "id": entry.get('resource_path', ''),
                "name": entry.get('resource_path', '').split('/')[-1],
                "resource_type": entry.get('resource_type', ''),
                "resource_version": entry.get('resource_version', ''),
                "meta": entry.get('meta', ''),
                "timestamp": entry.get('timestamp', ''),
                "description": description,
                "created_at": entry.get('timestamp', ''),
                "updated_at": entry.get('timestamp', ''),
                "status": meta.get('status', 'active'),
                "tasks_count": meta.get('tasks_count', 0)
            }
            playbooks.append(playbook)

        return playbooks
    except Exception as e:
        logger.error(f"Error getting playbooks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog/playbooks/{playbook_id:path}", response_class=JSONResponse)
async def get_catalog_playbook(playbook_id: str, version: Optional[str] = None):
    """Get playbook by ID, optionally by version"""
    try:
        logger.info(f"Received playbook_id: '{playbook_id}'")
        if playbook_id.startswith("playbooks/"):
            playbook_id = playbook_id[10:]
            logger.info(f"Fixed playbook_id: '{playbook_id}'")

        from .service import get_catalog_service
        catalog_service = get_catalog_service()

        if not version:
            version = await catalog_service.get_latest_version(playbook_id)

        entry = await catalog_service.fetch_entry(playbook_id, version)
        if not entry:
            raise HTTPException(
                status_code=404, detail=f"Playbook '{playbook_id}' with version '{version}' not found.")

        try:
            content = entry.get('content') or ''
            if isinstance(content, bytes):
                content = content.decode('utf-8', errors='ignore')
            entry['payload'] = yaml.safe_load(content) or {}
        except Exception:
            pass

        return entry
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting playbook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog/playbooks/{playbook_id:path}/content", response_class=JSONResponse)
async def get_catalog_playbook_content(playbook_id: str, request: Request, version: Optional[str] = None):
    """Get playbook raw content"""
    try:
        logger.info(f"Received playbook_id for content: '{playbook_id}'")
        if playbook_id.startswith("playbooks/"):
            playbook_id = playbook_id[10:]
            logger.info(f"Fixed playbook_id for content: '{playbook_id}'")
        body = None
        try:
            body = await request.json()
        except Exception:
            pass
        if not version and isinstance(body, dict):
            version = body.get('version')
        from .service import get_catalog_service
        catalog_service = get_catalog_service()
        if not version:
            version = await catalog_service.get_latest_version(playbook_id)
        entry = await catalog_service.fetch_entry(playbook_id, version)
        if not entry:
            raise HTTPException(
                status_code=404, detail=f"Playbook '{playbook_id}' with version '{version}' not found.")

        return {
            "path": playbook_id,
            "version": version,
            "content": entry.get('content')
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting playbook content: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/catalog/playbooks/{playbook_id:path}/content", response_class=JSONResponse)
async def save_catalog_playbook_content(playbook_id: str, request: Request):
    """Save playbook content (stores new version)."""
    try:
        logger.info(f"Received playbook_id for save: '{playbook_id}'")
        if playbook_id.startswith("playbooks/"):
            playbook_id = playbook_id[10:]
            logger.info(f"Fixed playbook_id for save: '{playbook_id}'")
        body = await request.json()
        content = body.get("content")
        if not content:
            raise HTTPException(status_code=400, detail="Content is required.")
        # Normalize YAML so resource_path matches URL id
        try:
            parsed = yaml.safe_load(content) or {}
            if isinstance(parsed, dict):
                if 'metadata' in parsed and isinstance(parsed['metadata'], dict):
                    parsed['metadata']['path'] = playbook_id
                    parsed['metadata'].setdefault(
                        'name', playbook_id.split('/')[-1])
                else:
                    meta = parsed.get('metadata') if isinstance(
                        parsed.get('metadata'), dict) else {}
                    meta['path'] = playbook_id
                    meta.setdefault('name', playbook_id.split('/')[-1])
                    parsed['metadata'] = meta
                parsed['path'] = playbook_id
                parsed.setdefault('name', playbook_id.split('/')[-1])
                content = yaml.safe_dump(parsed, sort_keys=False)
        except Exception as norm_err:
            logger.warning(
                f"Failed to normalize playbook path in YAML: {norm_err}")
        from .service import get_catalog_service
        catalog_service = get_catalog_service()
        # Use consistent resource type capitalization
        result = await catalog_service.register_resource(content, "Playbook")
        return {"status": "success", "message": f"Playbook '{playbook_id}' content updated.", "resource_path": result.get("resource_path"), "resource_version": result.get("resource_version")}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving playbooks content: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog/playbooks/{playbook_id:path}", response_class=JSONResponse)
async def get_catalog_playbook(playbook_id: str, version: Optional[str] = None):
    """Get playbook by ID, optionally by version

    Fallback: if a request meant for the /content endpoint is misrouted here (because of
    path matching order or stale server code) we detect the trailing '/content' segment
    and internally serve the raw content response to avoid a 404 like:
      Playbook '.../content' with version 'x.y.z' not found.
    """
    try:
        logger.info(f"Received playbook_id: '{playbook_id}'")
        if playbook_id.startswith("playbooks/"):
            playbook_id = playbook_id[10:]
            logger.info(f"Fixed playbook_id: '{playbook_id}'")

        # Fallback handling for misrouted content requests
        if playbook_id.endswith("/content") or playbook_id.endswith("/content/"):
            original_id = playbook_id.rstrip('/').rsplit('/content', 1)[0]
            logger.warning(
                "Misrouted playbook content request detected for '%s'; serving content via fallback.",
                original_id
            )
            from .service import get_catalog_service
            catalog_service = get_catalog_service()
            if not version:
                version = await catalog_service.get_latest_version(original_id)
            entry = await catalog_service.fetch_entry(original_id, version)
            if not entry:
                raise HTTPException(
                    status_code=404, detail=f"Playbook '{original_id}' with version '{version}' not found.")
            return {"path": original_id, "version": version, "content": entry.get('content')}

        from .service import get_catalog_service
        catalog_service = get_catalog_service()
        if not version:
            version = await catalog_service.get_latest_version(playbook_id)
        entry = await catalog_service.fetch_entry(playbook_id, version)
        if not entry:
            raise HTTPException(
                status_code=404, detail=f"Playbook '{playbook_id}' with version '{version}' not found.")
        try:
            content = entry.get('content') or ''
            if isinstance(content, bytes):
                content = content.decode('utf-8', errors='ignore')
            entry['payload'] = yaml.safe_load(content) or {}
        except Exception:
            pass
        return entry
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting playbook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog/widgets", response_class=JSONResponse)
async def get_catalog_widgets():
    """Get catalog visualization widgets"""
    try:
        playbook_count = 0
        active_count = 0
        draft_count = 0

        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT COUNT(DISTINCT resource_path) FROM catalog WHERE resource_type = 'widget'"
                    )
                    row = await cursor.fetchone()
                    playbook_count = row[0] if row else 0

                    await cursor.execute(
                        """
 SELECT meta FROM catalog
 WHERE resource_type = 'widget'
                        """
                    )
                    results = await cursor.fetchall()

                    for row in results:
                        meta_str = row[0]
                        if meta_str:
                            try:
                                meta = json.loads(meta_str) if isinstance(
                                    meta_str, str) else meta_str
                                status = meta.get('status', 'active')
                                if status == 'active':
                                    active_count += 1
                                elif status == 'draft':
                                    draft_count += 1
                            except (json.JSONDecodeError, TypeError):
                                active_count += 1
                        else:
                            active_count += 1
        except Exception as db_error:
            logger.warning(
                f"Error getting catalog stats from database: {db_error}")
            playbook_count = 0

        return [
            {
                "id": "catalog-summary",
                "type": "metric",
                "title": "Total Playbooks",
                "data": {
                    "value": playbook_count
                },
                "config": {
                    "format": "number",
                    "color": "#1890ff"
                }
            },
            {
                "id": "active-playbooks",
                "type": "metric",
                "title": "Active Playbooks",
                "data": {
                    "value": active_count
                },
                "config": {
                    "format": "number",
                    "color": "#52c41a"
                }
            },
            {
                "id": "draft-playbooks",
                "type": "metric",
                "title": "Draft Playbooks",
                "data": {
                    "value": draft_count
                },
                "config": {
                    "format": "number",
                    "color": "#faad14"
                }
            }
        ]
    except Exception as e:
        logger.error(f"Error getting catalog widgets: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Dependency/helper for runtime to get playbook entry


async def get_playbook_entry_from_catalog(playbook_id: str) -> Dict[str, Any]:
    logger.info(f"Dependency received playbook_id: '{playbook_id}'")
    path_to_lookup = playbook_id.replace('%2F', '/')
    if path_to_lookup.startswith("playbooks/"):
        path_to_lookup = path_to_lookup.removeprefix("playbooks/")
        logger.info(f"Trimmed playbook_id to: '{path_to_lookup}'")
    version_to_lookup = None
    if ':' in path_to_lookup:
        path_parts = path_to_lookup.rsplit(':', 1)
        if path_parts[1].replace('.', '').isdigit():
            path_to_lookup = path_parts[0]
            logger.info(
                f"Parsed and cleaned path to '{path_to_lookup}' from malformed ID.")

    catalog_service = get_catalog_service()
    latest_version = await catalog_service.get_latest_version(path_to_lookup)
    logger.info(
        f"Using latest version for '{path_to_lookup}': {latest_version}")

    entry = await catalog_service.fetch_entry(path_to_lookup, latest_version)
    if not entry:
        raise HTTPException(
            status_code=404,
            detail=f"Playbook '{path_to_lookup}' with version '{latest_version}' not found in catalog."
        )
    return entry
