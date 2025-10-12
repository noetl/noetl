from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
import json
from noetl.core.logger import setup_logger
from noetl.core.common import get_async_db_connection
from noetl.api.routers.broker import execute_playbook_via_broker
from noetl.api.routers.catalog import get_playbook_entry_from_catalog

logger = setup_logger(__name__, include_location=True)
router = APIRouter()


@router.post("/executions/run", response_class=JSONResponse)
async def execute_playbook(request: Request):
    """
    Execute a playbook via the broker system.
    Body:
      { playbook_id: str, parameters?: dict, merge?: bool }
    """
    try:
        body = await request.json()
        playbook_id = body.get("playbook_id")
        parameters = body.get("parameters", {})
        merge = body.get("merge", False)
        parent_execution_id = body.get("parent_execution_id")
        parent_event_id = body.get("parent_event_id")
        parent_step = body.get("parent_step")

        if not playbook_id:
            raise HTTPException(
                status_code=400,
                detail="playbook_id is required."
            )

        logger.debug(f"EXECUTE_PLAYBOOK: Received request to execute playbook_id={playbook_id} with parameters={parameters}")

        # Fetch playbook entry from catalog
        entry = await get_playbook_entry_from_catalog(playbook_id)
        playbook_content = entry.get("content", "")

        # Execute playbook via broker
        result = execute_playbook_via_broker(
            playbook_content=playbook_content,
            playbook_path=playbook_id,
            playbook_version=entry.get("version", "latest"),
            input_payload=parameters,
            sync_to_postgres=True,
            merge=merge,
            parent_execution_id=parent_execution_id,
            parent_event_id=parent_event_id,
            parent_step=parent_step
        )

        # Persist workload record for this execution (server-side tracking)
        try:
            exec_id = result.get("execution_id")
            if exec_id:
                from noetl.core.common import get_async_db_connection
                async with get_async_db_connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """
                            INSERT INTO workload (execution_id, data)
                            VALUES (%s, %s)
                            ON CONFLICT (execution_id) DO UPDATE SET data = EXCLUDED.data
                            """,
                            (exec_id, json.dumps(parameters or {}))
                        )
                        try:
                            await conn.commit()
                        except Exception:
                            pass
        except Exception as _we:
            logger.warning(f"Failed to upsert workload for execution: { _we }")

        execution = {
            "id": result.get("execution_id", ""),
            "playbook_id": playbook_id,
            "playbook_name": playbook_id.split("/")[-1],
            "status": "running",
            "start_time": result.get("timestamp", ""),
            "progress": 0,
            "result": result
        }

        logger.debug(f"EXECUTE_PLAYBOOK: Returning execution={execution}")
        return execution

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing playbook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/execute", response_class=JSONResponse)
async def execute_playbook_by_path_version(request: Request):
    """
    Execute a playbook by path and version for UI compatibility.
    Body:
      { path: str, version?: str, input_payload?: dict, merge?: bool, sync_to_postgres?: bool }
    Returns:
      { execution_id: str, created_at: str, result?: dict }
    """
    try:
        body = await request.json()
        path = body.get("path")
        version = body.get("version", "latest")
        input_payload = body.get("input_payload", {})
        merge = body.get("merge", False)
        sync_to_postgres = body.get("sync_to_postgres", True)

        if not path:
            raise HTTPException(
                status_code=400,
                detail="path is required."
            )

        logger.debug(f"EXECUTE: Received request to execute path={path} version={version} with input_payload={input_payload}")

        # Fetch playbook entry from catalog using path and version
        try:
            if version == "latest":
                # Get latest version for this path
                async with get_async_db_connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """
                            SELECT version, content 
                            FROM noetl.catalog 
                            WHERE path = %s 
                            ORDER BY created_at DESC 
                            LIMIT 1
                            """,
                            (path,)
                        )
                        row = await cur.fetchone()
                        if not row:
                            raise HTTPException(
                                status_code=404,
                                detail=f"Playbook '{path}' not found in catalog."
                            )
                        version, playbook_content = row
            else:
                # Get specific version
                async with get_async_db_connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """
                            SELECT content 
                            FROM noetl.catalog 
                            WHERE path = %s AND version = %s
                            """,
                            (path, version)
                        )
                        row = await cur.fetchone()
                        if not row:
                            raise HTTPException(
                                status_code=404,
                                detail=f"Playbook '{path}' with version '{version}' not found in catalog."
                            )
                        playbook_content = row[0]
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error fetching playbook from catalog: {e}")
            raise HTTPException(status_code=500, detail="Error fetching playbook from catalog")

        # Execute playbook via broker
        result = execute_playbook_via_broker(
            playbook_content=playbook_content,
            playbook_path=path,
            playbook_version=version,
            input_payload=input_payload,
            sync_to_postgres=sync_to_postgres,
            merge=merge
        )

        # Return execution_id for UI compatibility
        execution_id = result.get("execution_id", "")
        timestamp = result.get("timestamp", "")

        logger.debug(f"EXECUTE: Returning execution_id={execution_id}")
        return {
            "execution_id": execution_id,
            "timestamp": timestamp,
            "result": result if not sync_to_postgres else None  # Don't return full result if syncing to DB
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing playbook: {e}")
        raise HTTPException(status_code=500, detail=str(e))
