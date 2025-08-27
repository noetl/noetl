
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse
import base64
import json
import yaml
from datetime import datetime
from psycopg.types.json import Json
from noetl.common import (
    deep_merge,
    get_pgdb_connection,
    get_db_connection,
    get_async_db_connection,
    get_snowflake_id_str,
    get_snowflake_id,
)

from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from noetl.common import deep_merge, get_pgdb_connection, get_db_connection
from noetl.logger import setup_logger


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
            import base64
            content = base64.b64decode(content_base64).decode('utf-8')
        elif not content:
            raise HTTPException(
                status_code=400,
                detail="The content or content_base64 must be provided."
            )

        catalog_service = get_catalog_service()
        result = catalog_service.register_resource(content, resource_type)
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
        entries = catalog_service.list_entries(resource_type)
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


@router.get("/catalog/playbooks", response_class=JSONResponse)
async def get_catalog_playbooks():
    """Get all playbooks"""
    try:
        catalog_service = get_catalog_service()
        entries = catalog_service.list_entries('Playbook')

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


@router.post("/catalog/playbooks", response_class=JSONResponse)
async def create_catalog_playbook(request: Request):
    """Create a new playbooks"""
    try:
        body = await request.json()
        name = body.get("name", "New Playbook")
        description = body.get("description", "")
        status = body.get("status", "draft")

        content = f"""# {name}
name: "{name.lower().replace(' ', '-')}"
description: "{description}"
tasks:
  - name: "sample-task"
    type: "log"
    config:
      message: "Hello from NoETL!"
"""

        catalog_service = get_catalog_service()
        result = catalog_service.register_resource(content, "playbooks")

        playbook = {
            "id": result.get("resource_path", ""),
            "name": name,
            "description": description,
            "created_at": result.get("timestamp", ""),
            "updated_at": result.get("timestamp", ""),
            "status": status,
            "tasks_count": 1,
            "version": result.get("resource_version", "")
        }

        return playbook
    except Exception as e:
        logger.error(f"Error creating playbooks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/catalog/playbooks/validate", response_class=JSONResponse)
async def validate_catalog_playbook(request: Request):
    """Validate playbooks content"""
    try:
        body = await request.json()
        content = body.get("content")

        if not content:
            raise HTTPException(
                status_code=400,
                detail="Content is required."
            )

        try:
            yaml.safe_load(content)
            return {"valid": True}
        except Exception as yaml_error:
            return {
                "valid": False,
                "errors": [str(yaml_error)]
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating playbooks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog/playbooks/content", response_class=JSONResponse)
async def get_catalog_playbook_content(playbook_id: str = Query(...)):
    """Get playbook content"""
    try:
        logger.info(f"Received playbook_id: '{playbook_id}'")
        if playbook_id.startswith("playbooks/"):
            playbook_id = playbook_id[10:]
            logger.info(f"Fixed playbook_id: '{playbook_id}'")

        catalog_service = get_catalog_service()
        latest_version = await catalog_service.get_latest_version(playbook_id)
        logger.info(f"Latest version for '{playbook_id}': '{latest_version}'")

        entry = catalog_service.fetch_entry(playbook_id, latest_version)

        if not entry:
            raise HTTPException(
                status_code=404,
                detail=f"Playbook '{playbook_id}' not found."
            )

        return {"content": entry.get('content', '')}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting playbook content: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog/playbook", response_class=JSONResponse)
async def get_catalog_playbook(
        playbook_id: str = Query(...),
        # entry: Dict[str, Any] = Depends(get_playbook_entry_from_catalog)
):
    """Get a single playbook by ID"""
    try:
        entry: Dict[str, Any] = await get_playbook_entry_from_catalog(playbook_id=playbook_id)
        meta = entry.get('meta', {})
        playbook_data = {
            "id": entry.get('resource_path', ''),
            "name": entry.get('resource_path', '').split('/')[-1],
            "description": meta.get('description', ''),
            "created_at": entry.get('timestamp', ''),
            "updated_at": entry.get('timestamp', ''),
            "status": meta.get('status', 'active'),
            "tasks_count": meta.get('tasks_count', 0),
            "version": entry.get('resource_version', '')
        }
        return playbook_data
    except Exception as e:
        logger.error(f"Error processing playbook entry: {e}")
        raise HTTPException(status_code=500, detail="Error processing playbook data.")


@router.put("/catalog/playbooks/{playbook_id:path}/content", response_class=JSONResponse)
async def save_catalog_playbook_content(playbook_id: str, request: Request):
    """Save playbooks content"""
    try:
        logger.info(f"Received playbook_id for save: '{playbook_id}'")
        if playbook_id.startswith("playbooks/"):
            playbook_id = playbook_id[10:]
            logger.info(f"Fixed playbook_id for save: '{playbook_id}'")

        body = await request.json()
        content = body.get("content")

        if not content:
            raise HTTPException(
                status_code=400,
                detail="Content is required."
            )
        catalog_service = get_catalog_service()
        result = catalog_service.register_resource(content, "playbooks")

        return {
            "status": "success",
            "message": f"Playbook '{playbook_id}' content updated.",
            "resource_path": result.get("resource_path"),
            "resource_version": result.get("resource_version")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving playbooks content: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalog/widgets", response_class=JSONResponse)
async def get_catalog_widgets():
    """Get catalog visualization widgets"""
    try:
        playbook_count = 0
        active_count = 0
        draft_count = 0

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT COUNT(DISTINCT resource_path) FROM catalog WHERE resource_type = 'widget'"
                    )
                    playbook_count = cursor.fetchone()[0]

                    cursor.execute(
                        """
 SELECT meta FROM catalog
 WHERE resource_type = 'widget'
                        """
                    )
                    results = cursor.fetchall()

                    for row in results:
                        meta_str = row[0]
                        if meta_str:
                            try:
                                meta = json.loads(meta_str) if isinstance(meta_str, str) else meta_str
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
            logger.warning(f"Error getting catalog stats from database: {db_error}")
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

class CatalogService:
    def __init__(self, pgdb_conn_string: str | None = None):
        self.pgdb_conn_string = pgdb_conn_string or get_pgdb_connection()

    async def get_latest_version(self, resource_path: str) -> str:
        try:
            async with get_async_db_connection(self.pgdb_conn_string) as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT COUNT(*) FROM catalog WHERE resource_path = %s",
                        (resource_path,)
                    )
                    row = await cursor.fetchone()
                    count = int(row[0]) if row else 0
                    if count == 0:
                        return "0.1.0"

                    await cursor.execute(
                        "SELECT resource_version FROM catalog WHERE resource_path = %s",
                        (resource_path,)
                    )
                    versions = [r[0] for r in (await cursor.fetchall() or [])]
                    if not versions:
                        return "0.1.0"

                    def _version_key(v: str):
                        parts = (v or "0").split('.')
                        parts += ['0'] * (3 - len(parts))
                        try:
                            return tuple(map(int, parts[:3]))
                        except Exception:
                            return (0, 0, 0)

                    latest = max(versions, key=_version_key)
                    return latest
        except Exception:
            return "0.1.0"

    def fetch_entry(self, path: str, version: str) -> Optional[Dict[str, Any]]:
        try:
            with get_db_connection(self.pgdb_conn_string) as conn:
                with conn.cursor(row_factory=dict_row) as cursor:
                    cursor.execute(
                        """
                        SELECT resource_path, resource_type, resource_version, content, payload, meta
                        FROM catalog
                        WHERE resource_path = %s AND resource_version = %s
                        """,
                        (path, version)
                    )
                    result = cursor.fetchone()
                    if not result and '/' in path:
                        filename = path.split('/')[-1]
                        cursor.execute(
                            """
                            SELECT resource_path, resource_type, resource_version, content, payload, meta
                            FROM catalog
                            WHERE resource_path = %s AND resource_version = %s
                            """,
                            (filename, version)
                        )
                        result = cursor.fetchone()
                    if result:
                        return dict(result)
                    return None
        except Exception:
            return None

    def increment_version(self, version: str) -> str:
        try:
            parts = (version or "0").split('.')
            while len(parts) < 3:
                parts.append('0')
            major, minor, patch = map(int, parts[:3])
            patch += 1
            return f"{major}.{minor}.{patch}"
        except Exception:
            return f"{version}.1"

    def register_resource(self, content: str, resource_type: str = "Playbook") -> Dict[str, Any]:
        try:
            resource_data = yaml.safe_load(content)
            resource_path = resource_data.get("path", resource_data.get("name", "unknown"))
            # Determine latest version synchronously from DB
            latest = None
            try:
                with get_db_connection(self.pgdb_conn_string) as _conn:
                    with _conn.cursor() as _cur:
                        _cur.execute("SELECT resource_version FROM catalog WHERE resource_path = %s", (resource_path,))
                        _versions = [r[0] for r in (_cur.fetchall() or [])]
                        if _versions:
                            def _version_key(v: str):
                                p = (v or "0").split('.')
                                p += ['0'] * (3 - len(p))
                                try:
                                    return tuple(map(int, p[:3]))
                                except Exception:
                                    return (0, 0, 0)
                            latest = max(_versions, key=_version_key)
            except Exception:
                latest = None
            latest = latest or "0.1.0"
            resource_version = latest if latest == '0.1.0' else self.increment_version(latest)

            with get_db_connection(self.pgdb_conn_string) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("INSERT INTO resource (name) VALUES (%s) ON CONFLICT DO NOTHING", (resource_type,))

                    attempt = 0
                    while attempt < 5:
                        cursor.execute(
                            "SELECT COUNT(*) FROM catalog WHERE resource_path = %s AND resource_version = %s",
                            (resource_path, resource_version)
                        )
                        row = cursor.fetchone()
                        if not row or int(row[0]) == 0:
                            break
                        resource_version = self.increment_version(resource_version)
                        attempt += 1
                    if attempt >= 5:
                        raise RuntimeError("Failed to find unique version")

                    cursor.execute(
                        """
                        INSERT INTO catalog
                        (resource_path, resource_type, resource_version, content, payload, meta)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            resource_path,
                            resource_type,
                            resource_version,
                            content,
                            Json(resource_data),
                            Json({"registered_at": datetime.utcnow().isoformat()}),
                        )
                    )
                    try:
                        conn.commit()
                    except Exception:
                        pass

            return {
                "status": "success",
                "message": f"Resource '{resource_path}' version '{resource_version}' registered.",
                "resource_path": resource_path,
                "resource_version": resource_version,
                "resource_type": resource_type,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def list_entries(self, resource_type: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            with get_db_connection(self.pgdb_conn_string) as conn:
                with conn.cursor(row_factory=dict_row) as cursor:
                    if resource_type:
                        cursor.execute(
                            """
                            SELECT resource_path, resource_type, resource_version, content, payload, meta, timestamp
                            FROM catalog WHERE resource_type = %s ORDER BY timestamp DESC
                            """,
                            (resource_type,)
                        )
                    else:
                        cursor.execute(
                            """
                            SELECT resource_path, resource_type, resource_version, content, payload, meta, timestamp
                            FROM catalog ORDER BY timestamp DESC
                            """
                        )
                    rows = cursor.fetchall() or []
                    return [dict(r) for r in rows]
        except Exception:
            return []

def get_catalog_service() -> CatalogService:
    return CatalogService()


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
            logger.info(f"Parsed and cleaned path to '{path_to_lookup}' from malformed ID.")

    catalog_service = get_catalog_service()
    latest_version = await catalog_service.get_latest_version(path_to_lookup)
    logger.info(f"Using latest version for '{path_to_lookup}': {latest_version}")

    entry = catalog_service.fetch_entry(path_to_lookup, latest_version)
    if not entry:
        raise HTTPException(
            status_code=404,
            detail=f"Playbook '{path_to_lookup}' with version '{latest_version}' not found in catalog."
        )
    return entry
