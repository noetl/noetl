import os
import json
import yaml
import logging
import tempfile
import asyncio
import subprocess
import psycopg
from typing import Dict, Any, Optional, List, Union
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from noetl.common import setup_logger, deep_merge
from noetl.agent import NoETLAgent

logger = setup_logger(__name__, include_location=True)

router = APIRouter()


DEFAULT_PGDB = "dbname=noetl user=noetl password=noetl host=localhost port=5434"

class CatalogService:

    def __init__(self, pgdb_conn_string: str = DEFAULT_PGDB):
        self.pgdb_conn_string = pgdb_conn_string

    def get_latest_version(self, resource_path: str) -> str:
        conn = None
        try:
            conn = psycopg.connect(self.pgdb_conn_string)

            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM catalog WHERE resource_path = %s",
                    (resource_path,)
                )
                count = cursor.fetchone()[0]
                logger.debug(f"Found {count} entries for resource_path '{resource_path}'")

                if count == 0:
                    logger.debug(f"No entries found for resource_path '{resource_path}', returning default version '0.1.0'")
                    return "0.1.0"

                cursor.execute(
                    "SELECT resource_version FROM catalog WHERE resource_path = %s",
                    (resource_path,)
                )
                versions = [row[0] for row in cursor.fetchall()]
                logger.debug(f"All versions for resource_path '{resource_path}': {versions}")

                cursor.execute(
                    """
                    WITH parsed_versions AS (
                        SELECT 
                            resource_version,
                            CAST(SPLIT_PART(resource_version, '.', 1) AS INTEGER) AS major,
                            CAST(SPLIT_PART(resource_version, '.', 2) AS INTEGER) AS minor,
                            CAST(SPLIT_PART(resource_version, '.', 3) AS INTEGER) AS patch
                        FROM catalog
                        WHERE resource_path = %s
                    )
                    SELECT resource_version
                    FROM parsed_versions
                    ORDER BY major DESC, minor DESC, patch DESC
                    LIMIT 1
                    """,
                    (resource_path,)
                )
                result = cursor.fetchone()

                if result:
                    latest_version = result[0]
                    logger.debug(f"Latest version for resource_path '{resource_path}': '{latest_version}'")
                    return latest_version

                logger.debug(f"No valid version found for resource_path '{resource_path}', returning default version '0.1.0'")
                return "0.1.0"
        except Exception as e:
            logger.exception(f"Error getting latest version for resource_path '{resource_path}': {e}")
            return "0.1.0"
        finally:
            if conn:
                try:
                    conn.close()
                except Exception as close_error:
                    logger.exception(f"Error closing connection: {close_error}")

    def increment_version(self, version: str) -> str:
        try:
            parts = version.split('.')
            while len(parts) < 3:
                parts.append('0')
            major, minor, patch = map(int, parts[:3])
            patch += 1
            return f"{major}.{minor}.{patch}"
        except Exception as e:
            logger.exception(f"Error incrementing version: {e}")
            return f"{version}.1"

    def register_resource(self, content: str, resource_type: str = "playbook") -> Dict[str, Any]:
        conn = None
        try:
            conn = psycopg.connect(self.pgdb_conn_string)
            resource_data = yaml.safe_load(content)
            resource_path = resource_data.get("path", resource_data.get("name", "unknown"))
            logger.debug(f"Extracted resource_path: '{resource_path}'")
            latest_version = self.get_latest_version(resource_path)
            logger.debug(f"Latest version for resource_path '{resource_path}': '{latest_version}'")
            resource_version = self.increment_version(latest_version)
            logger.debug(f"Incremented version: '{resource_version}'")
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM catalog WHERE resource_path = %s AND resource_version = %s",
                    (resource_path, resource_version)
                )
                count = cursor.fetchone()[0]
                max_attempts = 10
                attempt = 1
                while count > 0 and attempt <= max_attempts:
                    logger.warning(f"Version '{resource_version}' already exists for resource_path '{resource_path}', incrementing again (attempt {attempt}/{max_attempts})")
                    resource_version = self.increment_version(resource_version)
                    logger.debug(f"New incremented version: '{resource_version}'")

                    cursor.execute(
                        "SELECT COUNT(*) FROM catalog WHERE resource_path = %s AND resource_version = %s",
                        (resource_path, resource_version)
                    )
                    count = cursor.fetchone()[0]
                    attempt += 1

                if attempt > max_attempts:
                    logger.error(f"Failed to find an available version after {max_attempts} attempts")
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to find an available version after {max_attempts} attempts"
                    )

            logger.info(f"Registering resource '{resource_path}' with version '{resource_version}' (previous: '{latest_version}')")

            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO resource (name) VALUES (%s) ON CONFLICT DO NOTHING",
                    (resource_type,)
                )
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
                        json.dumps(resource_data),
                        json.dumps({"registered_at": "now()"})
                    )
                )
                conn.commit()

            return {
                "status": "success",
                "message": f"Resource '{resource_path}' version '{resource_version}' registered successfully.",
                "resource_path": resource_path,
                "resource_version": resource_version,
                "resource_type": resource_type
            }

        except Exception as e:
            logger.exception(f"Error registering resource: {e}")
            if conn:
                try:
                    conn.rollback()
                    logger.info("Transaction rolled back due to error")
                except Exception as rollback_error:
                    logger.exception(f"Error rolling back transaction: {rollback_error}")
            raise HTTPException(
                status_code=500,
                detail=f"Error registering resource: {e}"
            )
        finally:
            if conn:
                try:
                    conn.close()
                    logger.debug("Connection closed")
                except Exception as close_error:
                    logger.exception(f"Error closing connection: {close_error}")

    def fetch_entry(self, path: str, version: str) -> Optional[Dict[str, Any]]:
        conn = None
        try:
            conn = psycopg.connect(self.pgdb_conn_string)

            with conn.cursor() as cursor:
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
                    logger.info(f"Exact path not found, trying to match filename: {filename}")

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
                return {
                    "resource_path": result[0],
                    "resource_type": result[1],
                    "resource_version": result[2],
                    "content": result[3],
                    "payload": result[4],
                    "meta": result[5]
                }
            return None

        except Exception as e:
            logger.exception(f"Error fetching catalog entry: {e}")
            return None
        finally:
            if conn:
                try:
                    conn.close()
                except Exception as close_error:
                    logger.exception(f"Error closing connection: {close_error}")

    def list_entries(self, resource_type: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = None
        try:
            conn = psycopg.connect(self.pgdb_conn_string)

            with conn.cursor() as cursor:
                if resource_type:
                    cursor.execute(
                        """
                        SELECT resource_path, resource_type, resource_version, meta, timestamp
                        FROM catalog
                        WHERE resource_type = %s
                        ORDER BY timestamp DESC
                        """,
                        (resource_type,)
                    )
                else:
                    cursor.execute(
                        """
                        SELECT resource_path, resource_type, resource_version, meta, timestamp
                        FROM catalog
                        ORDER BY timestamp DESC
                        """
                    )

                results = cursor.fetchall()

            entries = []
            for row in results:
                entries.append({
                    "resource_path": row[0],
                    "resource_type": row[1],
                    "resource_version": row[2],
                    "meta": row[3],
                    "timestamp": row[4]
                })

            return entries

        except Exception as e:
            logger.exception(f"Error listing catalog entries: {e}")
            return []
        finally:
            if conn:
                try:
                    conn.close()
                except Exception as close_error:
                    logger.exception(f"Error closing connection: {close_error}")

def get_catalog_service() -> CatalogService:
    return CatalogService(DEFAULT_PGDB)

class EventService:
    _events = {}

    def __init__(self, pgdb_conn_string: str = DEFAULT_PGDB):
        self.pgdb_conn_string = pgdb_conn_string
        self.events = EventService._events

    def emit(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            event_id = event_data.get("event_id", f"evt_{os.urandom(16).hex()}")
            event_data["event_id"] = event_id
            event_type = event_data.get("event_type", "UNKNOWN")
            state = event_data.get("state", "CREATED")
            parent_id = event_data.get("parent_id")
            meta = event_data.get("meta", {})
            payload = event_data.get("payload", {})
            self.events[event_id] = event_data
            logger.info(f"Event emitted: {event_id} - {event_type} - {state}")

            return event_data

        except Exception as e:
            logger.exception(f"Error emitting event: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error emitting event: {e}"
            )

    def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        return self.events.get(event_id)

def get_event_service() -> EventService:
    return EventService(DEFAULT_PGDB)
class AgentService:

    def __init__(self, pgdb_conn_string: str = DEFAULT_PGDB):
        self.pgdb_conn_string = pgdb_conn_string

    def execute_agent(
        self, 
        playbook_content: str, 
        playbook_path: str, 
        playbook_version: str, 
        input_payload: Optional[Dict[str, Any]] = None,
        sync_to_postgres: bool = True,
        merge: bool = False
    ) -> Dict[str, Any]:
        try:
            with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as temp_file:
                temp_file.write(playbook_content.encode('utf-8'))
                temp_file_path = temp_file.name
            try:
                pgdb_conn = self.pgdb_conn_string if sync_to_postgres else None
                agent = NoETLAgent(temp_file_path, mock_mode=False, pgdb=pgdb_conn)
                workload = agent.playbook.get('workload', {})
                if input_payload:
                    if merge:
                        logger.info("Merge mode: deep merging input payload with workload")
                        merged_workload = deep_merge(workload, input_payload)
                        for key, value in merged_workload.items():
                            agent.update_context(key, value)
                        agent.update_context('workload', merged_workload)
                        agent.store_workload(merged_workload)
                    else:
                        logger.info("Override mode: replacing workload keys with input payload")
                        merged_workload = workload.copy()
                        for key, value in input_payload.items():
                            merged_workload[key] = value
                        for key, value in merged_workload.items():
                            agent.update_context(key, value)
                        agent.update_context('workload', merged_workload)
                        agent.store_workload(merged_workload)
                else:
                    logger.info("No input payload provided, using default workload from playbook")
                    for key, value in workload.items():
                        agent.update_context(key, value)
                    agent.update_context('workload', workload)
                    agent.store_workload(workload)

                results = agent.run()

                export_path = None

                return {
                    "status": "success",
                    "message": f"Agent executed successfully for playbook '{playbook_path}' version '{playbook_version}'.",
                    "result": results,
                    "execution_id": agent.execution_id,
                    "export_path": export_path
                }
            finally:
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)

        except Exception as e:
            logger.exception(f"Error executing agent: {e}")
            return {
                "status": "error",
                "message": f"Error executing agent for playbook '{playbook_path}' version '{playbook_version}': {e}",
                "error": str(e)
            }

def get_agent_service() -> AgentService:
    return AgentService(DEFAULT_PGDB)

@router.post("/catalog/register", response_class=JSONResponse)
async def register_resource(
    request: Request,
    content_base64: str = None,
    content: str = None,
    resource_type: str = "playbook"
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
                detail="Either content or content_base64 must be provided."
            )

        catalog_service = get_catalog_service()
        result = catalog_service.register_resource(content, resource_type)
        return result

    except Exception as e:
        logger.exception(f"Error registering resource: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error registering resource: {e}"
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

@router.get("/catalog/{path}/{version}", response_class=JSONResponse)
async def get_resource(
    request: Request,
    path: str,
    version: str
):
    try:
        catalog_service = get_catalog_service()
        entry = catalog_service.fetch_entry(path, version)
        if not entry:
            raise HTTPException(
                status_code=404,
                detail=f"Resource '{path}' with version '{version}' not found."
            )
        return entry

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching resource: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching resource: {e}"
        )


@router.get("/events/{event_id}", response_class=JSONResponse)
async def get_event(
    request: Request,
    event_id: str
):
    try:
        event_service = get_event_service()
        event = event_service.get_event(event_id)
        if not event:
            raise HTTPException(
                status_code=404,
                detail=f"Event '{event_id}' not found."
            )
        return event

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching event: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching event: {e}"
        )


@router.post("/agent/execute", response_class=JSONResponse)
async def execute_agent(
    request: Request,
    path: str = None,
    version: str = None,
    input_payload: Dict[str, Any] = None,
    sync_to_postgres: bool = True,
    merge: bool = False
):
    try:
        if not path:
            try:
                body = await request.json()
                path = body.get("path", path)
                version = body.get("version", version)
                input_payload = body.get("input_payload", input_payload)
                sync_to_postgres = body.get("sync_to_postgres", sync_to_postgres)
                merge = body.get("merge", merge)
            except:
                pass

        if not path:
            raise HTTPException(
                status_code=400,
                detail="Path is a required parameter."
            )

        catalog_service = get_catalog_service()
        if not version:
            version = catalog_service.get_latest_version(path)
            logger.info(f"Version not specified, using latest version: {version}")

        entry = catalog_service.fetch_entry(path, version)
        if not entry:
            raise HTTPException(
                status_code=404,
                detail=f"Playbook '{path}' with version '{version}' not found."
            )

        agent_service = get_agent_service()
        result = agent_service.execute_agent(
            playbook_content=entry.get("content"),
            playbook_path=path,
            playbook_version=version,
            input_payload=input_payload,
            sync_to_postgres=sync_to_postgres,
            merge=merge
        )

        return result

    except Exception as e:
        logger.exception(f"Error executing agent: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error executing agent for playbook '{path}' version '{version}': {e}"
        )

@router.post("/agent/execute-async", response_class=JSONResponse)
async def execute_agent_async(
    request: Request,
    background_tasks: BackgroundTasks,
    path: str = None,
    version: str = None,
    input_payload: Dict[str, Any] = None,
    sync_to_postgres: bool = True,
    merge: bool = False
):

    try:
        if not path:
            try:
                body = await request.json()
                path = body.get("path", path)
                version = body.get("version", version)
                input_payload = body.get("input_payload", input_payload)
                sync_to_postgres = body.get("sync_to_postgres", sync_to_postgres)
                merge = body.get("merge", merge)
            except:
                pass

        if not path:
            raise HTTPException(
                status_code=400,
                detail="Path is a required parameter."
            )

        catalog_service = get_catalog_service()

        if not version:
            version = catalog_service.get_latest_version(path)
            logger.info(f"Version not specified, using latest version: {version}")

        entry = catalog_service.fetch_entry(path, version)
        if not entry:
            raise HTTPException(
                status_code=404,
                detail=f"Playbook '{path}' with version '{version}' not found."
            )

        event_service = get_event_service()
        initial_event_data = {
            "event_type": "AgentExecutionRequested",
            "state": "REQUESTED",
            "meta": {
                "resource_path": path,
                "resource_version": version,
            },
            "payload": input_payload
        }

        initial_event = event_service.emit(initial_event_data)

        def execute_agent_task():
            try:
                with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as temp_file:
                    temp_file.write(entry.get("content").encode('utf-8'))
                    temp_file_path = temp_file.name

                try:
                    pgdb_conn = DEFAULT_PGDB if sync_to_postgres else None
                    agent = NoETLAgent(temp_file_path, mock_mode=False, pgdb=pgdb_conn)
                    workload = agent.playbook.get('workload', {})
                    if input_payload:
                        if merge:
                            logger.info("Merge mode: deep merging input payload with workload")
                            merged_workload = deep_merge(workload, input_payload)

                            for key, value in merged_workload.items():
                                agent.update_context(key, value)

                            agent.update_context('workload', merged_workload)
                            agent.store_workload(merged_workload)
                        else:
                            logger.info("Override mode: replacing workload keys with input payload")
                            merged_workload = workload.copy()
                            for key, value in input_payload.items():
                                merged_workload[key] = value
                            for key, value in merged_workload.items():
                                agent.update_context(key, value)
                            agent.update_context('workload', merged_workload)
                            agent.store_workload(merged_workload)
                    else:
                        logger.info("No input payload provided, using default workload from playbook")

                        for key, value in workload.items():
                            agent.update_context(key, value)

                        agent.update_context('workload', workload)
                        agent.store_workload(workload)

                    results = agent.run()

                    event_id = initial_event.get("event_id")

                    initial_event["state"] = "COMPLETED"
                    initial_event["event_type"] = "AgentExecutionCompleted"
                    initial_event["payload"] = results
                    initial_event["meta"]["execution_id"] = agent.execution_id

                    event_service.events[event_id] = initial_event

                    logger.info(f"Event updated: {event_id} - AgentExecutionCompleted - COMPLETED")

                finally:
                    if os.path.exists(temp_file_path):
                        os.unlink(temp_file_path)

            except Exception as e:
                logger.exception(f"Error in background agent execution: {e}")
                event_id = initial_event.get("event_id")
                initial_event["state"] = "ERROR"
                initial_event["event_type"] = "AgentExecutionError"
                initial_event["meta"]["error"] = str(e)
                initial_event["payload"] = {"error": str(e)}
                event_service.events[event_id] = initial_event
                logger.info(f"Event updated: {event_id} - AgentExecutionError - ERROR")

        background_tasks.add_task(execute_agent_task)

        return {
            "status": "accepted",
            "message": f"Agent execution started for playbook '{path}' version '{version}'.",
            "event_id": initial_event.get("event_id")
        }

    except Exception as e:
        logger.exception(f"Error starting agent execution: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error starting agent execution for playbook '{path}' version '{version}': {e}"
        )
