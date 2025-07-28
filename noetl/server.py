import os
import json
import yaml
import tempfile
from datetime import datetime
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from noetl.common import setup_logger, deep_merge, get_pgdb_connection, get_db_connection
from noetl.worker import Worker
from noetl.broker import Broker

logger = setup_logger(__name__, include_location=True)

router = APIRouter()

class CatalogService:
    def __init__(self, pgdb_conn_string: str | None = None):
        pass

    def get_latest_version(self, resource_path: str) -> str:
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT COUNT(*) FROM catalog WHERE resource_path = %s",
                        (resource_path,)
                    )
                    count = cursor.fetchone()[0]

                    if count == 0:
                        return "0.1.0"

                    cursor.execute(
                        "SELECT resource_version FROM catalog WHERE resource_path = %s",
                        (resource_path,)
                    )
                    versions = [row[0] for row in cursor.fetchall()]

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
                        return latest_version

                    return "0.1.0"
        except Exception as e:
            logger.exception(f"Error getting latest version for resource_path '{resource_path}': {e}")
            return "0.1.0"

    def fetch_entry(self, path: str, version: str) -> Optional[Dict[str, Any]]:
        try:
            with get_db_connection() as conn:
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
                        logger.info(f"Path not found. Trying to match filename: {filename}")

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
            logger.exception(f"Error fetching catalog entry: {e}.")
            return None

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


    def register_resource(self, content: str, resource_type: str = "playbooks") -> Dict[str, Any]:
        try:
            with get_db_connection() as conn:
                resource_data = yaml.safe_load(content)
                resource_path = resource_data.get("path", resource_data.get("name", "unknown"))
                latest_version = self.get_latest_version(resource_path)

                if latest_version != '0.1.0':
                    resource_version = self.increment_version(latest_version)
                else:
                    resource_version = latest_version

                attempt = 0
                max_attempts = 5
                with conn.cursor() as cursor:
                    while attempt < max_attempts:
                        cursor.execute(
                            "SELECT COUNT(*) FROM catalog WHERE resource_path = %s AND resource_version = %s",
                            (resource_path, resource_version)
                        )
                        count = int(cursor.fetchone()[0])
                        if count == 0:
                            break
                        resource_version = self.increment_version(resource_version)
                        attempt += 1

                    if attempt >= max_attempts:
                        logger.error(f"Failed to find version after {max_attempts} attempts")
                        raise HTTPException(
                            status_code=500,
                            detail=f"Failed to find version after {max_attempts} attempts"
                        )

                    logger.info(
                        f"Registering resource '{resource_path}' with version '{resource_version}' (previous: '{latest_version}')")

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
                    "message": f"Resource '{resource_path}' version '{resource_version}' registered.",
                    "resource_path": resource_path,
                    "resource_version": resource_version,
                    "resource_type": resource_type
                }

        except Exception as e:
            logger.exception(f"Error registering resource: {e}.")
            raise HTTPException(
                status_code=500,
                detail=f"Error registering resource: {e}."
            )
    def list_entries(self, resource_type: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    if resource_type:
                        cursor.execute(
                            """
                            SELECT resource_path, resource_type, resource_version, content, payload, meta, timestamp
                            FROM catalog
                            WHERE resource_type = %s
                            ORDER BY timestamp DESC
                            """,
                            (resource_type,)
                        )
                    else:
                        cursor.execute(
                            """
                            SELECT resource_path, resource_type, resource_version, content, payload, meta, timestamp
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
                        "content": row[3],
                        "payload": row[4],
                        "meta": row[5],
                        "timestamp": row[6]
                    })

                return entries

        except Exception as e:
            logger.exception(f"Error listing catalog entries: {e}")
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
    latest_version = catalog_service.get_latest_version(path_to_lookup)
    logger.info(f"Using latest version for '{path_to_lookup}': {latest_version}")

    entry = catalog_service.fetch_entry(path_to_lookup, latest_version)
    if not entry:
        raise HTTPException(
            status_code=404,
            detail=f"Playbook '{path_to_lookup}' with version '{latest_version}' not found in catalog."
        )
    return entry

class EventService:
    def __init__(self, pgdb_conn_string: str | None = None):
        pass

    def get_all_executions(self) -> List[Dict[str, Any]]:
        """
        Get all executions from the event_log table.
        
        Returns:
            A list of execution data dictionaries
        """
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        WITH latest_events AS (
                            SELECT 
                                execution_id,
                                MAX(timestamp) as latest_timestamp
                            FROM event_log
                            GROUP BY execution_id
                        )
                        SELECT 
                            e.execution_id,
                            e.event_type,
                            e.status,
                            e.timestamp,
                            e.metadata,
                            e.input_context,
                            e.output_result,
                            e.error
                        FROM event_log e
                        JOIN latest_events le ON e.execution_id = le.execution_id AND e.timestamp = le.latest_timestamp
                        ORDER BY e.timestamp DESC
                    """)

                    rows = cursor.fetchall()
                    executions = []

                    for row in rows:
                        execution_id = row[0]
                        metadata = json.loads(row[4]) if row[4] else {}
                        input_context = json.loads(row[5]) if row[5] else {}
                        output_result = json.loads(row[6]) if row[6] else {}
                        playbook_id = metadata.get('resource_path', input_context.get('path', ''))
                        playbook_name = playbook_id.split('/')[-1] if playbook_id else 'Unknown'
                        status = row[2]
                        if status == 'COMPLETED':
                            status = 'completed'
                        elif status == 'ERROR':
                            status = 'failed'
                        elif status == 'RUNNING':
                            status = 'running'
                        else:
                            status = 'pending'

                        start_time = row[3].isoformat() if row[3] else None
                        end_time = None
                        duration = None

                        cursor.execute("""
                            SELECT MIN(timestamp) FROM event_log WHERE execution_id = %s
                        """, (execution_id,))
                        min_time_row = cursor.fetchone()
                        if min_time_row and min_time_row[0]:
                            start_time = min_time_row[0].isoformat()

                        if status in ['completed', 'failed']:
                            cursor.execute("""
                                SELECT MAX(timestamp) FROM event_log WHERE execution_id = %s
                            """, (execution_id,))
                            max_time_row = cursor.fetchone()
                            if max_time_row and max_time_row[0]:
                                end_time = max_time_row[0].isoformat()

                                if start_time:
                                    start_dt = datetime.fromisoformat(start_time)
                                    end_dt = datetime.fromisoformat(end_time)
                                    duration = (end_dt - start_dt).total_seconds()

                        progress = 100 if status in ['completed', 'failed'] else 0
                        if status == 'running':
                            cursor.execute("""
                                SELECT COUNT(*) FROM event_log WHERE execution_id = %s
                            """, (execution_id,))
                            total_steps = cursor.fetchone()[0]

                            cursor.execute("""
                                SELECT COUNT(*) FROM event_log 
                                WHERE execution_id = %s AND status IN ('COMPLETED', 'ERROR')
                            """, (execution_id,))
                            completed_steps = cursor.fetchone()[0]

                            if total_steps > 0:
                                progress = int((completed_steps / total_steps) * 100)

                        execution_data = {
                            "id": execution_id,
                            "playbook_id": playbook_id,
                            "playbook_name": playbook_name,
                            "status": status,
                            "start_time": start_time,
                            "end_time": end_time,
                            "duration": duration,
                            "progress": progress,
                            "result": output_result,
                            "error": row[7]
                        }

                        executions.append(execution_data)

                    return executions

        except Exception as e:
            logger.exception(f"Error getting all executions: {e}")
            return []

    def emit(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            event_id = event_data.get("event_id", f"evt_{os.urandom(16).hex()}")
            event_data["event_id"] = event_id
            event_type = event_data.get("event_type", "UNKNOWN")
            status = event_data.get("status", "CREATED")
            parent_event_id = event_data.get("parent_id") or event_data.get("parent_event_id")
            execution_id = event_data.get("execution_id", event_id)
            node_id = event_data.get("node_id", event_id)
            node_name = event_data.get("node_name", event_type)
            node_type = event_data.get("node_type", "event")
            duration = event_data.get("duration", 0.0)
            metadata = event_data.get("meta", {})
            error = event_data.get("error")
            input_context = json.dumps(event_data.get("context", {}))
            output_result = json.dumps(event_data.get("result", {}))
            metadata_str = json.dumps(metadata)

            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT COUNT(*) FROM event_log 
                        WHERE execution_id = %s AND event_id = %s
                    """, (execution_id, event_id))

                    exists = cursor.fetchone()[0] > 0

                    if exists:
                        cursor.execute("""
                            UPDATE event_log SET
                                event_type = %s,
                                status = %s,
                                duration = %s,
                                input_context = %s,
                                output_result = %s,
                                metadata = %s,
                                error = %s,
                                timestamp = CURRENT_TIMESTAMP
                            WHERE execution_id = %s AND event_id = %s
                        """, (
                            event_type,
                            status,
                            duration,
                            input_context,
                            output_result,
                            metadata_str,
                            error,
                            execution_id,
                            event_id
                        ))
                    else:
                        cursor.execute("""
                            INSERT INTO event_log (
                                execution_id, event_id, parent_event_id, timestamp, event_type,
                                node_id, node_name, node_type, status, duration,
                                input_context, output_result, metadata, error
                            ) VALUES (
                                %s, %s, %s, CURRENT_TIMESTAMP, %s,
                                %s, %s, %s, %s, %s,
                                %s, %s, %s, %s
                            )
                        """, (
                            execution_id,
                            event_id,
                            parent_event_id,
                            event_type,
                            node_id,
                            node_name,
                            node_type,
                            status,
                            duration,
                            input_context,
                            output_result,
                            metadata_str,
                            error
                        ))

                    conn.commit()

            logger.info(f"Event emitted: {event_id} - {event_type} - {status}")
            return event_data

        except Exception as e:
            logger.exception(f"Error emitting event: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error emitting event: {e}"
            )

    def get_events_by_execution_id(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """
        Get all events for a specific execution.

        Args:
            execution_id: The ID of the execution

        Returns:
            A dictionary containing events or None if not found
        """
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT 
                            event_id, 
                            event_type, 
                            node_id, 
                            node_name, 
                            node_type, 
                            status, 
                            duration, 
                            timestamp, 
                            input_context, 
                            output_result, 
                            metadata, 
                            error
                        FROM event_log 
                        WHERE execution_id = %s
                        ORDER BY timestamp
                    """, (execution_id,))

                    rows = cursor.fetchall()
                    if rows:
                        events = []
                        for row in rows:
                            event_data = {
                                "event_id": row[0],
                                "event_type": row[1],
                                "node_id": row[2],
                                "node_name": row[3],
                                "node_type": row[4],
                                "status": row[5],
                                "duration": row[6],
                                "timestamp": row[7].isoformat() if row[7] else None,
                                "input_context": json.loads(row[8]) if row[8] else None,
                                "output_result": json.loads(row[9]) if row[9] else None,
                                "metadata": json.loads(row[10]) if row[10] else None,
                                "error": row[11],
                                "execution_id": execution_id,
                                "resource_path": None,
                                "resource_version": None
                            }

                            if event_data["metadata"] and "playbook_path" in event_data["metadata"]:
                                event_data["resource_path"] = event_data["metadata"]["playbook_path"]

                            if event_data["input_context"] and "path" in event_data["input_context"]:
                                event_data["resource_path"] = event_data["input_context"]["path"]

                            if event_data["input_context"] and "version" in event_data["input_context"]:
                                event_data["resource_version"] = event_data["input_context"]["version"]

                            events.append(event_data)

                        return {"events": events}

                    return None
        except Exception as e:
            logger.exception(f"Error getting events by execution_id: {e}")
            return None

    def get_event_by_id(self, event_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single event by its ID.

        Args:
            event_id: The ID of the event

        Returns:
            A dictionary containing the event or None if not found
        """
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT 
                            event_id, 
                            event_type, 
                            node_id, 
                            node_name, 
                            node_type, 
                            status, 
                            duration, 
                            timestamp, 
                            input_context, 
                            output_result, 
                            metadata, 
                            error,
                            execution_id
                        FROM event_log 
                        WHERE event_id = %s
                    """, (event_id,))

                    row = cursor.fetchone()
                    if row:
                        event_data = {
                            "event_id": row[0],
                            "event_type": row[1],
                            "node_id": row[2],
                            "node_name": row[3],
                            "node_type": row[4],
                            "status": row[5],
                            "duration": row[6],
                            "timestamp": row[7].isoformat() if row[7] else None,
                            "input_context": json.loads(row[8]) if row[8] else None,
                            "output_result": json.loads(row[9]) if row[9] else None,
                            "metadata": json.loads(row[10]) if row[10] else None,
                            "error": row[11],
                            "execution_id": row[12],
                            "resource_path": None,
                            "resource_version": None
                        }
                        if event_data["metadata"] and "playbook_path" in event_data["metadata"]:
                            event_data["resource_path"] = event_data["metadata"]["playbook_path"]

                        if event_data["input_context"] and "path" in event_data["input_context"]:
                            event_data["resource_path"] = event_data["input_context"]["path"]

                        if event_data["input_context"] and "version" in event_data["input_context"]:
                            event_data["resource_version"] = event_data["input_context"]["version"]
                        return {"events": [event_data]}

                    return None
        except Exception as e:
            logger.exception(f"Error getting event by ID: {e}")
            return None

    def get_event(self, id_param: str) -> Optional[Dict[str, Any]]:
        """
        Get events by execution_id or event_id (legacy method for backward compatibility).

        Args:
            id_param: Either an execution_id or an event_id

        Returns:
            A dictionary containing events or None if not found
        """
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT COUNT(*) FROM event_log WHERE execution_id = %s
                    """, (id_param,))
                    count = cursor.fetchone()[0]

                    if count > 0:
                        events = self.get_events_by_execution_id(id_param)
                        if events:
                            return events

                event = self.get_event_by_id(id_param)
                if event:
                    return event

                with get_db_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("""
                            SELECT DISTINCT execution_id FROM event_log 
                            WHERE event_id = %s
                        """, (id_param,))
                        execution_ids = [row[0] for row in cursor.fetchall()]

                        if execution_ids:
                            events = self.get_events_by_execution_id(execution_ids[0])
                            if events:
                                return events

                return None
        except Exception as e:
            logger.exception(f"Error in get_event: {e}")
            return None

def get_event_service() -> EventService:
    return EventService()

def get_catalog_service_dependency() -> CatalogService:
    return CatalogService()

def get_event_service_dependency() -> EventService:
    return EventService()


class AgentService:

    def __init__(self, pgdb_conn_string: str | None = None):
        self.pgdb_conn_string = pgdb_conn_string if pgdb_conn_string else get_pgdb_connection()
        self.agent = None

    def store_transition(self, params: tuple):
        """
        Store the transition in the database.

        Args:
            params: A tuple containing the transition parameters
        """
        if self.agent:
            self.agent.store_transition(params)

    def get_step_results(self) -> Dict[str, Any]:
        """
        Get the results of all steps.

        Returns:
            A dictionary mapping the step names to results
        """
        if self.agent:
            return self.agent.get_step_results()
        return {}

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
                self.agent = Worker(temp_file_path, mock_mode=False, pgdb=pgdb_conn)
                agent = self.agent
                workload = agent.playbook.get('workload', {})
                if input_payload:
                    if merge:
                        logger.info("Merge mode: deep merging input payload with workload.")
                        merged_workload = deep_merge(workload, input_payload)
                        for key, value in merged_workload.items():
                            agent.update_context(key, value)
                        agent.update_context('workload', merged_workload)
                        agent.store_workload(merged_workload)
                    else:
                        logger.info("Override mode: replacing workload keys with input payload.")
                        merged_workload = workload.copy()
                        for key, value in input_payload.items():
                            merged_workload[key] = value
                        for key, value in merged_workload.items():
                            agent.update_context(key, value)
                        agent.update_context('workload', merged_workload)
                        agent.store_workload(merged_workload)
                else:
                    logger.info("No input payload provided. Default workload from playbooks is used.")
                    for key, value in workload.items():
                        agent.update_context(key, value)
                    agent.update_context('workload', workload)
                    agent.store_workload(workload)
                server_url = os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082')
                daemon = Broker(agent, server_url=server_url)
                results = daemon.run()

                export_path = None

                return {
                    "status": "success",
                    "message": f"Agent executed for playbooks '{playbook_path}' version '{playbook_version}'.",
                    "result": results,
                    "execution_id": agent.execution_id,
                    "export_path": export_path
                }
            finally:
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)

        except Exception as e:
            logger.exception(f"Error executing agent: {e}.")
            return {
                "status": "error",
                "message": f"Error executing agent for playbooks '{playbook_path}' version '{playbook_version}': {e}.",
                "error": str(e)
            }

def get_agent_service() -> AgentService:
    return AgentService(get_pgdb_connection())

def get_agent_service_dependency() -> AgentService:
    return AgentService()

@router.post("/catalog/register", response_class=JSONResponse)
async def register_resource(
    request: Request,
    content_base64: str = None,
    content: str = None,
    resource_type: str = "playbooks"
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

@router.get("/catalog/{path:path}/{version}", response_class=JSONResponse)
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
        logger.exception(f"Error fetching resource: {e}.")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching resource: {e}."
        )


@router.get("/events/by-execution/{execution_id}", response_class=JSONResponse)
async def get_events_by_execution(
    request: Request,
    execution_id: str
):
    """
    Get all events for a specific execution.
    """
    try:
        event_service = get_event_service()
        events = event_service.get_events_by_execution_id(execution_id)
        if not events:
            raise HTTPException(
                status_code=404,
                detail=f"No events found for execution '{execution_id}'."
            )
        return events

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching events by execution: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching events by execution: {e}"
        )

@router.get("/events/by-id/{event_id}", response_class=JSONResponse)
async def get_event_by_id(
    request: Request,
    event_id: str
):
    """
    Get a single event by its ID.
    """
    try:
        event_service = get_event_service()
        event = event_service.get_event_by_id(event_id)
        if not event:
            raise HTTPException(
                status_code=404,
                detail=f"Event with ID '{event_id}' not found."
            )
        return event

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching event by ID: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching event by ID: {e}"
        )

@router.get("/events/{event_id}", response_class=JSONResponse)
async def get_event(
    request: Request,
    event_id: str
):
    """
    Legacy endpoint for getting events by execution_id or event_id.
    Use /events/by-execution/{execution_id} or /events/by-id/{event_id} instead.
    """
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

@router.get("/events/query", response_class=JSONResponse)
async def get_event_by_query(
    request: Request,
    event_id: str = None
):
    if not event_id:
        raise HTTPException(
            status_code=400,
            detail="event_id query parameter is required."
        )

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
        logger.exception(f"Error fetching event: {e}.")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching event: {e}."
        )

@router.get("/execution/data/{execution_id}", response_class=JSONResponse)
async def get_execution_data(
    request: Request,
    execution_id: str
):
    try:
        event_service = get_event_service()
        event = event_service.get_event(execution_id)
        if not event:
            raise HTTPException(
                status_code=404,
                detail=f"Execution '{execution_id}' not found."
            )
        return event

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching execution data: {e}.")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching execution data: {e}."
        )

@router.post("/events", response_class=JSONResponse)
async def create_event(
    request: Request
):
    try:
        body = await request.json()
        event_service = get_event_service()
        result = event_service.emit(body)
        return result
    except Exception as e:
        logger.exception(f"Error creating event: {e}.")
        raise HTTPException(
            status_code=500,
            detail=f"Error creating event: {e}."
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
            detail=f"Error executing agent for playbooks '{path}' version '{version}': {e}."
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
            "status": "REQUESTED",
            "meta": {
                "resource_path": path,
                "resource_version": version,
            },
            "result": input_payload,
            "node_type": "playbooks",
            "node_name": path
        }

        initial_event = event_service.emit(initial_event_data)

        def execute_agent_task():
            try:
                with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as temp_file:
                    temp_file.write(entry.get("content").encode('utf-8'))
                    temp_file_path = temp_file.name

                try:
                    pgdb_conn = get_pgdb_connection() if sync_to_postgres else None
                    agent = Worker(temp_file_path, mock_mode=False, pgdb=pgdb_conn)
                    workload = agent.playbook.get('workload', {})
                    if input_payload:
                        if merge:
                            logger.info("Merge mode: deep merging input payload with workload.")
                            merged_workload = deep_merge(workload, input_payload)

                            for key, value in merged_workload.items():
                                agent.update_context(key, value)

                            agent.update_context('workload', merged_workload)
                            agent.store_workload(merged_workload)
                        else:
                            logger.info("Override mode: replacing workload keys with input payload.")
                            merged_workload = workload.copy()
                            for key, value in input_payload.items():
                                merged_workload[key] = value
                            for key, value in merged_workload.items():
                                agent.update_context(key, value)
                            agent.update_context('workload', merged_workload)
                            agent.store_workload(merged_workload)
                    else:
                        logger.info("No input payload provided. Default workload from playbooks is used.")

                        for key, value in workload.items():
                            agent.update_context(key, value)

                        agent.update_context('workload', workload)
                        agent.store_workload(workload)

                    results = agent.run()
                    event_id = initial_event.get("event_id")
                    update_event = {
                        "event_id": event_id,
                        "execution_id": agent.execution_id,
                        "event_type": "agent_execution_completed",
                        "status": "COMPLETED",
                        "result": results,
                        "meta": {
                            "resource_path": path,
                            "resource_version": version,
                            "execution_id": agent.execution_id
                        },
                        "node_type": "playbooks",
                        "node_name": path
                    }

                    event_service.emit(update_event)
                    logger.info(f"Event updated: {event_id} - agent_execution_completed - COMPLETED")

                finally:
                    if os.path.exists(temp_file_path):
                        os.unlink(temp_file_path)

            except Exception as e:
                logger.exception(f"Error in background agent execution: {e}.")
                event_id = initial_event.get("event_id")

                error_event = {
                    "event_id": event_id,
                    "execution_id": event_id,
                    "event_type": "agent_execution_error",
                    "status": "ERROR",
                    "error": str(e),
                    "result": {"error": str(e)},
                    "meta": {
                        "resource_path": path,
                        "resource_version": version,
                        "error": str(e)
                    },
                    "node_type": "playbooks",
                    "node_name": path
                }

                event_service.emit(error_event)
                logger.info(f"Event updated: {event_id} - agent_execution_error - ERROR")

        background_tasks.add_task(execute_agent_task)

        return {
            "status": "accepted",
            "message": f"Agent execution started for playbooks '{path}' version '{version}'.",
            "event_id": initial_event.get("event_id")
        }

    except Exception as e:
        logger.exception(f"Error starting agent execution: {e}.")
        raise HTTPException(
            status_code=500,
            detail=f"Error starting agent execution for playbooks '{path}' version '{version}': {e}"
        )


@router.get("/dashboard/stats", response_class=JSONResponse)
async def get_dashboard_stats():
    """Get dashboard statistics"""
    try:
        return {
            "total_executions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
            "total_playbooks": 0,
            "active_workflows": 0
        }
    except Exception as e:
        logger.error(f"Error getting dashboard stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dashboard/widgets", response_class=JSONResponse)
async def get_dashboard_widgets():
    """Get dashboard widgets"""
    try:
        return []
    except Exception as e:
        logger.error(f"Error getting dashboard widgets: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/playbooks", response_class=JSONResponse)
async def get_playbooks():
    """Get all playbooks (legacy endpoint)"""
    return await get_catalog_playbooks()

@router.get("/catalog/playbooks", response_class=JSONResponse)
async def get_catalog_playbooks():
    """Get all playbooks"""
    try:
        catalog_service = get_catalog_service()
        entries = catalog_service.list_entries('playbooks')
        
        playbooks = []
        for entry in entries:
            meta = entry.get('meta', {})
            
            # Try to get description from payload (parsed YAML content) first, then from meta
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
            
            # Fallback to meta description if payload doesn't have it
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

@router.post("/executions/run", response_class=JSONResponse)
async def execute_playbook(request: Request):
    """Execute a playbooks"""
    try:
        body = await request.json()
        playbook_id = body.get("playbook_id")
        parameters = body.get("parameters", {})
        
        if not playbook_id:
            raise HTTPException(
                status_code=400,
                detail="playbook_id is required."
            )
        
        result = await execute_agent(
            request=request,
            path=playbook_id,
            input_payload=parameters,
            sync_to_postgres=True,
            merge=False
        )
        
        execution = {
            "id": result.get("execution_id", ""),
            "playbook_id": playbook_id,
            "playbook_name": playbook_id.split("/")[-1],
            "status": "running",
            "start_time": result.get("timestamp", ""),
            "progress": 0,
            "result": result
        }
        
        return execution
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing playbooks: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/catalog/playbooks", response_class=JSONResponse)
async def get_catalog_playbook(
    playbook_id: str = Query(..., alias="playbook_id"),
    # entry: Dict[str, Any] = Depends(get_playbook_entry_from_catalog)
):
    try:
        entry: Dict[str, Any] = get_playbook_entry_from_catalog(playbook_id=playbook_id)
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
        logger.error(f"Error processing playbooks entry: {e}")
        raise HTTPException(status_code=500, detail="Error processing playbooks data.")

@router.get("/catalog/playbooks/content", response_class=JSONResponse)
async def get_catalog_playbook_content(playbook_id: str = Query(..., alias="playbook_id")):
    """Get playbooks content"""
    try:
        logger.info(f"Received playbook_id: '{playbook_id}'")
        if playbook_id.startswith("playbooks/"):
            playbook_id = playbook_id[10:]
            logger.info(f"Fixed playbook_id: '{playbook_id}'")
        
        catalog_service = get_catalog_service()
        latest_version = catalog_service.get_latest_version(playbook_id)
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
        logger.error(f"Error getting playbooks content: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
        # Get actual playbook count from catalog
        playbook_count = 0
        active_count = 0
        draft_count = 0
        
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Count total playbooks
                    cursor.execute(
                        "SELECT COUNT(DISTINCT resource_path) FROM catalog WHERE resource_type = 'playbooks'"
                    )
                    playbook_count = cursor.fetchone()[0]
                    
                    # Count by status - we'll need to parse the meta field
                    cursor.execute(
                        """
                        SELECT meta FROM catalog 
                        WHERE resource_type = 'playbooks'
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
                                active_count += 1  # Default to active if can't parse
                        else:
                            active_count += 1  # Default to active if no meta
        except Exception as db_error:
            logger.warning(f"Error getting catalog stats from database: {db_error}")
            # Fallback to basic count if database query fails
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

@router.get("/executions", response_class=JSONResponse)
async def get_executions():
    """Get all executions"""
    try:
        event_service = get_event_service()
        executions = event_service.get_all_executions()
        return executions
    except Exception as e:
        logger.error(f"Error getting executions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/executions/{execution_id}", response_class=JSONResponse)
async def get_execution(execution_id: str):
    """Get a specific execution by ID"""
    try:
        event_service = get_event_service()
        events = event_service.get_events_by_execution_id(execution_id)
        
        if not events:
            raise HTTPException(
                status_code=404,
                detail=f"Execution '{execution_id}' not found."
            )
        
        latest_event = None
        for event in events.get("events", []):
            if not latest_event or (event.get("timestamp", "") > latest_event.get("timestamp", "")):
                latest_event = event
        
        if not latest_event:
            raise HTTPException(
                status_code=404,
                detail=f"No events found for execution '{execution_id}'."
            )
        
        metadata = latest_event.get("metadata", {})
        input_context = latest_event.get("input_context", {})
        output_result = latest_event.get("output_result", {})
        
        playbook_id = metadata.get('resource_path', input_context.get('path', ''))
        playbook_name = playbook_id.split('/')[-1] if playbook_id else 'Unknown'
        
        status = latest_event.get("status", "")
        if status == 'COMPLETED':
            status = 'completed'
        elif status == 'ERROR':
            status = 'failed'
        elif status == 'RUNNING':
            status = 'running'
        else:
            status = 'pending'
        
        timestamps = [event.get("timestamp", "") for event in events.get("events", []) if event.get("timestamp")]
        timestamps.sort()
        
        start_time = timestamps[0] if timestamps else None
        end_time = timestamps[-1] if timestamps and status in ['completed', 'failed'] else None
        
        duration = None
        if start_time and end_time:
            try:
                start_dt = datetime.fromisoformat(start_time)
                end_dt = datetime.fromisoformat(end_time)
                duration = (end_dt - start_dt).total_seconds()
            except Exception as e:
                logger.error(f"Error calculating duration: {e}")
        
        progress = 100 if status in ['completed', 'failed'] else 0
        if status == 'running':
            total_steps = len(events.get("events", []))
            completed_steps = sum(1 for event in events.get("events", []) if event.get("status") in ['COMPLETED', 'ERROR'])
            
            if total_steps > 0:
                progress = int((completed_steps / total_steps) * 100)
        
        execution_data = {
            "id": execution_id,
            "playbook_id": playbook_id,
            "playbook_name": playbook_name,
            "status": status,
            "start_time": start_time,
            "end_time": end_time,
            "duration": duration,
            "progress": progress,
            "result": output_result,
            "error": latest_event.get("error"),
            "events": events.get("events", [])
        }
        
        return execution_data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting execution: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health", response_class=JSONResponse)
async def api_health():
    """API health check endpoint"""
    return {"status": "ok"}
