import os
import json
import yaml
import tempfile
import os
import json
import yaml
import tempfile
import psycopg
import base64
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from noetl.common import deep_merge, get_pgdb_connection, get_db_connection
from noetl.logger import setup_logger
from noetl.broker import Broker, execute_playbook_via_broker
from noetl.api import router as api_router
# Removed external cron/timezone libraries (croniter, pytz) per requirement; using simple internal parser.

logger = setup_logger(__name__, include_location=True)

router = APIRouter()
router.include_router(api_router)


# class EventService:
#     def __init__(self, pgdb_conn_string: str | None = None):
#         pass
#
#     def _normalize_status(self, raw: str | None) -> str:
#         if not raw:
#             return 'pending'
#         s = str(raw).strip().lower()
#         if s in {'completed', 'complete', 'success', 'succeeded', 'done'}:
#             return 'completed'
#         if s in {'error', 'failed', 'failure'}:
#             return 'failed'
#         if s in {'running', 'run', 'in_progress', 'in-progress', 'progress', 'started', 'start'}:
#             return 'running'
#         if s in {'created', 'queued', 'pending', 'init', 'initialized', 'new'}:
#             return 'pending'
#         # fallback
#         return 'pending'
#
#     def get_all_executions(self) -> List[Dict[str, Any]]:
#         """
#         Get all executions from the event_log table.
#
#         Returns:
#             A list of execution data dictionaries
#         """
#         try:
#             with get_db_connection() as conn:
#                 with conn.cursor() as cursor:
#                     cursor.execute("""
#                         WITH latest_events AS (
#                             SELECT
#                                 execution_id,
#                                 MAX(timestamp) as latest_timestamp
#                             FROM event_log
#                             GROUP BY execution_id
#                         )
#                         SELECT
#                             e.execution_id,
#                             e.event_type,
#                             e.status,
#                             e.timestamp,
#                             e.metadata,
#                             e.input_context,
#                             e.output_result,
#                             e.error
#                         FROM event_log e
#                         JOIN latest_events le ON e.execution_id = le.execution_id AND e.timestamp = le.latest_timestamp
#                         ORDER BY e.timestamp DESC
#                     """)
#
#                     rows = cursor.fetchall()
#                     executions = []
#
#                     for row in rows:
#                         execution_id = row[0]
#                         metadata = json.loads(row[4]) if row[4] else {}
#                         input_context = json.loads(row[5]) if row[5] else {}
#                         output_result = json.loads(row[6]) if row[6] else {}
#                         playbook_id = metadata.get('resource_path', input_context.get('path', ''))
#                         playbook_name = playbook_id.split('/')[-1] if playbook_id else 'Unknown'
#                         raw_status = row[2]
#                         status = self._normalize_status(raw_status)
#
#                         start_time = row[3].isoformat() if row[3] else None
#                         end_time = None
#                         duration = None
#
#                         cursor.execute("""
#                             SELECT MIN(timestamp) FROM event_log WHERE execution_id = %s
#                         """, (execution_id,))
#                         min_time_row = cursor.fetchone()
#                         if min_time_row and min_time_row[0]:
#                             start_time = min_time_row[0].isoformat()
#
#                         if status in ['completed', 'failed']:
#                             cursor.execute("""
#                                 SELECT MAX(timestamp) FROM event_log WHERE execution_id = %s
#                             """, (execution_id,))
#                             max_time_row = cursor.fetchone()
#                             if max_time_row and max_time_row[0]:
#                                 end_time = max_time_row[0].isoformat()
#
#                                 if start_time:
#                                     start_dt = datetime.fromisoformat(start_time)
#                                     end_dt = datetime.fromisoformat(end_time)
#                                     duration = (end_dt - start_dt).total_seconds()
#
#                         progress = 100 if status in ['completed', 'failed'] else 0
#                         if status == 'running':
#                             # Count total events & those considered finished (completed/failed)
#                             cursor.execute("""
#                                 SELECT status FROM event_log WHERE execution_id = %s
#                             """, (execution_id,))
#                             event_statuses = [self._normalize_status(r[0]) for r in cursor.fetchall()]
#                             total_steps = len(event_statuses)
#                             completed_steps = sum(1 for s in event_statuses if s in {'completed', 'failed'})
#                             if total_steps > 0:
#                                 progress = int((completed_steps / total_steps) * 100)
#
#                         execution_data = {
#                             "id": execution_id,
#                             "playbook_id": playbook_id,
#                             "playbook_name": playbook_name,
#                             "status": status,
#                             "start_time": start_time,
#                             "end_time": end_time,
#                             "duration": duration,
#                             "progress": progress,
#                             "result": output_result,
#                             "error": row[7]
#                         }
#
#                         executions.append(execution_data)
#
#                     return executions
#
#         except Exception as e:
#             logger.exception(f"Error getting all executions: {e}")
#             return []
#
#     def emit(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
#         try:
#             event_id = event_data.get("event_id", f"evt_{os.urandom(16).hex()}")
#             event_data["event_id"] = event_id
#             event_type = event_data.get("event_type", "UNKNOWN")
#             status = event_data.get("status", "CREATED")
#             parent_event_id = event_data.get("parent_id") or event_data.get("parent_event_id")
#             execution_id = event_data.get("execution_id", event_id)
#             node_id = event_data.get("node_id", event_id)
#             node_name = event_data.get("node_name", event_type)
#             node_type = event_data.get("node_type", "event")
#             duration = event_data.get("duration", 0.0)
#             metadata = event_data.get("meta", {})
#             error = event_data.get("error")
#             input_context = json.dumps(event_data.get("context", {}))
#             output_result = json.dumps(event_data.get("result", {}))
#             metadata_str = json.dumps(metadata)
#
#             with get_db_connection() as conn:
#                 with conn.cursor() as cursor:
#                     cursor.execute("""
#                         SELECT COUNT(*) FROM event_log
#                         WHERE execution_id = %s AND event_id = %s
#                     """, (execution_id, event_id))
#
#                     exists = cursor.fetchone()[0] > 0
#
#                     if exists:
#                         cursor.execute("""
#                             UPDATE event_log SET
#                                 event_type = %s,
#                                 status = %s,
#                                 duration = %s,
#                                 input_context = %s,
#                                 output_result = %s,
#                                 metadata = %s,
#                                 error = %s,
#                                 timestamp = CURRENT_TIMESTAMP
#                             WHERE execution_id = %s AND event_id = %s
#                         """, (
#                             event_type,
#                             status,
#                             duration,
#                             input_context,
#                             output_result,
#                             metadata_str,
#                             error,
#                             execution_id,
#                             event_id
#                         ))
#                     else:
#                         cursor.execute("""
#                             INSERT INTO event_log (
#                                 execution_id, event_id, parent_event_id, timestamp, event_type,
#                                 node_id, node_name, node_type, status, duration,
#                                 input_context, output_result, metadata, error
#                             ) VALUES (
#                                 %s, %s, %s, CURRENT_TIMESTAMP, %s,
#                                 %s, %s, %s, %s, %s,
#                                 %s, %s, %s, %s
#                             )
#                         """, (
#                             execution_id,
#                             event_id,
#                             parent_event_id,
#                             event_type,
#                             node_id,
#                             node_name,
#                             node_type,
#                             status,
#                             duration,
#                             input_context,
#                             output_result,
#                             metadata_str,
#                             error
#                         ))
#
#                     conn.commit()
#
#             logger.info(f"Event emitted: {event_id} - {event_type} - {status}")
#             return event_data
#
#         except Exception as e:
#             logger.exception(f"Error emitting event: {e}")
#             raise HTTPException(
#                 status_code=500,
#                 detail=f"Error emitting event: {e}"
#             )
#
#     def get_events_by_execution_id(self, execution_id: str) -> Optional[Dict[str, Any]]:
#         """
#         Get all events for a specific execution.
#
#         Args:
#             execution_id: The ID of the execution
#
#         Returns:
#             A dictionary containing events or None if not found
#         """
#         try:
#             with get_db_connection() as conn:
#                 with conn.cursor() as cursor:
#                     cursor.execute("""
#                         SELECT
#                             event_id,
#                             event_type,
#                             node_id,
#                             node_name,
#                             node_type,
#                             status,
#                             duration,
#                             timestamp,
#                             input_context,
#                             output_result,
#                             metadata,
#                             error
#                         FROM event_log
#                         WHERE execution_id = %s
#                         ORDER BY timestamp
#                     """, (execution_id,))
#
#                     rows = cursor.fetchall()
#                     if rows:
#                         events = []
#                         for row in rows:
#                             event_data = {
#                                 "event_id": row[0],
#                                 "event_type": row[1],
#                                 "node_id": row[2],
#                                 "node_name": row[3],
#                                 "node_type": row[4],
#                                 "status": row[5],
#                                 "duration": row[6],
#                                 "timestamp": row[7].isoformat() if row[7] else None,
#                                 "input_context": json.loads(row[8]) if row[8] else None,
#                                 "output_result": json.loads(row[9]) if row[9] else None,
#                                 "metadata": json.loads(row[10]) if row[10] else None,
#                                 "error": row[11],
#                                 "execution_id": execution_id,
#                                 "resource_path": None,
#                                 "resource_version": None,
#                                 "normalized_status": self._normalize_status(row[5])
#                             }
#
#                             if event_data["metadata"] and "playbook_path" in event_data["metadata"]:
#                                 event_data["resource_path"] = event_data["metadata"]["playbook_path"]
#
#                             if event_data["input_context"] and "path" in event_data["input_context"]:
#                                 event_data["resource_path"] = event_data["input_context"]["path"]
#
#                             if event_data["input_context"] and "version" in event_data["input_context"]:
#                                 event_data["resource_version"] = event_data["input_context"]["version"]
#
#                             events.append(event_data)
#
#                         return {"events": events}
#
#                     return None
#         except Exception as e:
#             logger.exception(f"Error getting events by execution_id: {e}")
#             return None
#
#     def get_event_by_id(self, event_id: str) -> Optional[Dict[str, Any]]:
#         """
#         Get a single event by its ID.
#
#         Args:
#             event_id: The ID of the event
#
#         Returns:
#             A dictionary containing the event or None if not found
#         """
#         try:
#             with get_db_connection() as conn:
#                 with conn.cursor() as cursor:
#                     cursor.execute("""
#                         SELECT
#                             event_id,
#                             event_type,
#                             node_id,
#                             node_name,
#                             node_type,
#                             status,
#                             duration,
#                             timestamp,
#                             input_context,
#                             output_result,
#                             metadata,
#                             error,
#                             execution_id
#                         FROM event_log
#                         WHERE event_id = %s
#                     """, (event_id,))
#
#                     row = cursor.fetchone()
#                     if row:
#                         event_data = {
#                             "event_id": row[0],
#                             "event_type": row[1],
#                             "node_id": row[2],
#                             "node_name": row[3],
#                             "node_type": row[4],
#                             "status": row[5],
#                             "duration": row[6],
#                             "timestamp": row[7].isoformat() if row[7] else None,
#                             "input_context": json.loads(row[8]) if row[8] else None,
#                             "output_result": json.loads(row[9]) if row[9] else None,
#                             "metadata": json.loads(row[10]) if row[10] else None,
#                             "error": row[11],
#                             "execution_id": row[12],
#                             "resource_path": None,
#                             "resource_version": None
#                         }
#                         if event_data["metadata"] and "playbook_path" in event_data["metadata"]:
#                             event_data["resource_path"] = event_data["metadata"]["playbook_path"]
#
#                         if event_data["input_context"] and "path" in event_data["input_context"]:
#                             event_data["resource_path"] = event_data["input_context"]["path"]
#
#                         if event_data["input_context"] and "version" in event_data["input_context"]:
#                             event_data["resource_version"] = event_data["input_context"]["version"]
#                         return {"events": [event_data]}
#
#                     return None
#         except Exception as e:
#             logger.exception(f"Error getting event by ID: {e}")
#             return None
#
#     def get_event(self, id_param: str) -> Optional[Dict[str, Any]]:
#         """
#         Get events by execution_id or event_id (legacy method for backward compatibility).
#
#         Args:
#             id_param: Either an execution_id or an event_id
#
#         Returns:
#             A dictionary containing events or None if not found
#         """
#         try:
#             with get_db_connection() as conn:
#                 with conn.cursor() as cursor:
#                     cursor.execute("""
#                         SELECT COUNT(*) FROM event_log WHERE execution_id = %s
#                     """, (id_param,))
#                     count = cursor.fetchone()[0]
#
#                     if count > 0:
#                         events = self.get_events_by_execution_id(id_param)
#                         if events:
#                             return events
#
#                 event = self.get_event_by_id(id_param)
#                 if event:
#                     return event
#
#                 with get_db_connection() as conn:
#                     with conn.cursor() as cursor:
#                         cursor.execute("""
#                             SELECT DISTINCT execution_id FROM event_log
#                             WHERE event_id = %s
#                         """, (id_param,))
#                         execution_ids = [row[0] for row in cursor.fetchall()]
#
#                         if execution_ids:
#                             events = self.get_events_by_execution_id(execution_ids[0])
#                             if events:
#                                 return events
#
#                 return None
#         except Exception as e:
#             logger.exception(f"Error in get_event: {e}")
#             return None
#
# def get_event_service() -> EventService:
#     return EventService()
#
# def get_catalog_service_dependency() -> CatalogService:
#     return CatalogService()
#
# def get_event_service_dependency() -> EventService:
#     return EventService()


# class AgentService:
#
#     def __init__(self, pgdb_conn_string: str | None = None):
#         self.pgdb_conn_string = pgdb_conn_string if pgdb_conn_string else get_pgdb_connection()
#         self.agent = None
#
#     def store_transition(self, params: tuple):
#         """
#         Store the transition in the database.
#
#         Args:
#             params: A tuple containing the transition parameters
#         """
#         if self.agent:
#             self.agent.store_transition(params)
#
#     def get_step_results(self) -> Dict[str, Any]:
#         """
#         Get the results of all steps.
#
#         Returns:
#             A dictionary mapping the step names to results
#         """
#         if self.agent:
#             return self.agent.get_step_results()
#         return {}
#
#     def execute_agent(
#         self,
#         playbook_content: str,
#         playbook_path: str,
#         playbook_version: str,
#         input_payload: Optional[Dict[str, Any]] = None,
#         sync_to_postgres: bool = True,
#         merge: bool = False
#     ) -> Dict[str, Any]:
#         try:
#             logger.debug("=== AGENT_SERVICE.EXECUTE_AGENT: Function entry ===")
#             logger.debug(f"AGENT_SERVICE.EXECUTE_AGENT: Parameters - playbook_path={playbook_path}, playbook_version={playbook_version}, input_payload={input_payload}, sync_to_postgres={sync_to_postgres}, merge={merge}")
#
#             temp_file_path = None
#             logger.debug("AGENT_SERVICE.EXECUTE_AGENT: Creating temporary file for playbook content")
#             with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as temp_file:
#                 temp_file.write(playbook_content.encode('utf-8'))
#                 temp_file_path = temp_file.name
#                 logger.debug(f"AGENT_SERVICE.EXECUTE_AGENT: Created temporary file at {temp_file_path}")
#
#             try:
#                 pgdb_conn = self.pgdb_conn_string if sync_to_postgres else None
#                 logger.debug(f"AGENT_SERVICE.EXECUTE_AGENT: Using pgdb_conn={pgdb_conn}")
#
#                 # NOTE: Worker class removed / not imported; if legacy functionality required, reintroduce minimal executor.
#                 agent = self.agent  # remains None; placeholder for future implementation
#                 logger.debug("AGENT_SERVICE.EXECUTE_AGENT: Worker functionality disabled (no Worker class).")
#
#                 workload = agent.playbook.get('workload', {})
#                 logger.debug(f"AGENT_SERVICE.EXECUTE_AGENT: Loaded workload from playbook: {workload}")
#
#                 if input_payload:
#                     if merge:
#                         logger.info("AGENT_SERVICE.EXECUTE_AGENT: Merge mode: deep merging input payload with workload.")
#                         logger.debug(f"AGENT_SERVICE.EXECUTE_AGENT: Input payload for merge: {input_payload}")
#                         merged_workload = deep_merge(workload, input_payload)
#                         logger.debug(f"AGENT_SERVICE.EXECUTE_AGENT: Merged workload: {merged_workload}")
#                         for key, value in merged_workload.items():
#                             agent.update_context(key, value)
#                             logger.debug(f"AGENT_SERVICE.EXECUTE_AGENT: Updated context with key={key}, value={value}")
#                         agent.update_context('workload', merged_workload)
#                         agent.store_workload(merged_workload)
#                     else:
#                         logger.info("AGENT_SERVICE.EXECUTE_AGENT: Override mode: replacing workload keys with input payload.")
#                         logger.debug(f"AGENT_SERVICE.EXECUTE_AGENT: Input payload for override: {input_payload}")
#                         merged_workload = workload.copy()
#                         for key, value in input_payload.items():
#                             merged_workload[key] = value
#                             logger.debug(f"AGENT_SERVICE.EXECUTE_AGENT: Overriding key={key} with value={value}")
#                         for key, value in merged_workload.items():
#                             agent.update_context(key, value)
#                             logger.debug(f"AGENT_SERVICE.EXECUTE_AGENT: Updated context with key={key}, value={value}")
#                         agent.update_context('workload', merged_workload)
#                         agent.store_workload(merged_workload)
#                 else:
#                     logger.info("AGENT_SERVICE.EXECUTE_AGENT: No input payload provided. Default workload from playbooks is used.")
#                     for key, value in workload.items():
#                         agent.update_context(key, value)
#                         logger.debug(f"AGENT_SERVICE.EXECUTE_AGENT: Updated context with key={key}, value={value}")
#                     agent.update_context('workload', workload)
#                     agent.store_workload(workload)
#
#                 server_url = os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082')
#                 logger.debug(f"AGENT_SERVICE.EXECUTE_AGENT: Using server_url={server_url}")
#
#                 logger.debug("AGENT_SERVICE.EXECUTE_AGENT: Initializing Broker")
#                 daemon = Broker(agent, server_url=server_url)
#
#                 logger.debug("AGENT_SERVICE.EXECUTE_AGENT: Calling daemon.run()")
#                 results = daemon.run()
#                 logger.debug(f"AGENT_SERVICE.EXECUTE_AGENT: daemon.run() returned results={results}")
#
#                 export_path = None
#
#                 result = {
#                     "status": "success",
#                     "message": f"Agent executed for playbooks '{playbook_path}' version '{playbook_version}'.",
#                     "result": results,
#                     "execution_id": agent.execution_id,
#                     "export_path": export_path
#                 }
#
#                 logger.debug(f"AGENT_SERVICE.EXECUTE_AGENT: Returning result={result}")
#                 logger.debug("=== AGENT_SERVICE.EXECUTE_AGENT: Function exit ===")
#                 return result
#             finally:
#                 if os.path.exists(temp_file_path):
#                     logger.debug(f"AGENT_SERVICE.EXECUTE_AGENT: Removing temporary file {temp_file_path}")
#                     os.unlink(temp_file_path)
#
#         except Exception as e:
#             logger.exception(f"AGENT_SERVICE.EXECUTE_AGENT: Error executing agent: {e}.")
#             error_result = {
#                 "status": "error",
#                 "message": f"Error executing agent for playbooks '{playbook_path}' version '{playbook_version}': {e}.",
#                 "error": str(e)
#             }
#             logger.debug(f"AGENT_SERVICE.EXECUTE_AGENT: Returning error result={error_result}")
#             logger.debug("=== AGENT_SERVICE.EXECUTE_AGENT: Function exit with error ===")
#             return error_result
#
# def get_agent_service() -> AgentService:
#     return AgentService(get_pgdb_connection())
#
# def get_agent_service_dependency() -> AgentService:
#     return AgentService()

# @router.post("/catalog/register", response_class=JSONResponse)
# async def register_resource(
#     request: Request,
#     content_base64: str = None,
#     content: str = None,
#     resource_type: str = "Playbook"
# ):
#     try:
#         if not content_base64 and not content:
#             try:
#                 body = await request.json()
#                 content_base64 = body.get("content_base64")
#                 content = body.get("content")
#                 resource_type = body.get("resource_type", resource_type)
#             except:
#                 pass
#
#         if content_base64:
#             import base64
#             content = base64.b64decode(content_base64).decode('utf-8')
#         elif not content:
#             raise HTTPException(
#                 status_code=400,
#                 detail="The content or content_base64 must be provided."
#             )
#
#         catalog_service = get_catalog_service()
#         result = await catalog_service.register_resource(content, resource_type)
#         return result
#
#     except Exception as e:
#         logger.exception(f"Error registering resource: {e}.")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Error registering resource: {e}."
#         )
#
# @router.get("/catalog/list", response_class=JSONResponse)
# async def list_resources(
#     request: Request,
#     resource_type: str = None
# ):
#     try:
#         catalog_service = get_catalog_service()
#         entries = await catalog_service.list_entries(resource_type)
#         return {"entries": entries}
#
#     except Exception as e:
#         logger.exception(f"Error listing resources: {e}")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Error listing resources: {e}"
#         )

# @router.get("/events/by-execution/{execution_id}", response_class=JSONResponse)
# async def get_events_by_execution(
#     request: Request,
#     execution_id: str
# ):
#     """
#     Get all events for a specific execution.
#     """
#     try:
#         event_service = get_event_service()
#         events = event_service.get_events_by_execution_id(execution_id)
#         if not events:
#             raise HTTPException(
#                 status_code=404,
#                 detail=f"No events found for execution '{execution_id}'."
#             )
#         return events
#
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.exception(f"Error fetching events by execution: {e}")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Error fetching events by execution: {e}"
#         )
#
# @router.get("/events/by-id/{event_id}", response_class=JSONResponse)
# async def get_event_by_id(
#     request: Request,
#     event_id: str
# ):
#     """
#     Get a single event by its ID.
#     """
#     try:
#         event_service = get_event_service()
#         event = event_service.get_event_by_id(event_id)
#         if not event:
#             raise HTTPException(
#                 status_code=404,
#                 detail=f"Event with ID '{event_id}' not found."
#             )
#         return event
#
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.exception(f"Error fetching event by ID: {e}")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Error fetching event by ID: {e}"
#         )
#
# @router.get("/events/{event_id}", response_class=JSONResponse)
# async def get_event(
#     request: Request,
#     event_id: str
# ):
#     """
#     Legacy endpoint for getting events by execution_id or event_id.
#     Use /events/by-execution/{execution_id} or /events/by-id/{event_id} instead.
#     """
#     try:
#         event_service = get_event_service()
#         event = event_service.get_event(event_id)
#         if not event:
#             raise HTTPException(
#                 status_code=404,
#                 detail=f"Event '{event_id}' not found."
#             )
#         return event
#
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.exception(f"Error fetching event: {e}")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Error fetching event: {e}"
#         )
#
# @router.get("/events/query", response_class=JSONResponse)
# async def get_event_by_query(
#     request: Request,
#     event_id: str = None
# ):
#     if not event_id:
#         raise HTTPException(
#             status_code=400,
#             detail="event_id query parameter is required."
#         )
#
#     try:
#         event_service = get_event_service()
#         event = event_service.get_event(event_id)
#         if not event:
#             raise HTTPException(
#                 status_code=404,
#                 detail=f"Event '{event_id}' not found."
#             )
#         return event
#
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.exception(f"Error fetching event: {e}.")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Error fetching event: {e}."
#         )

# @router.get("/execution/data/{execution_id}", response_class=JSONResponse)
# async def get_execution_data(
#     request: Request,
#     execution_id: str
# ):
#     try:
#         event_service = get_event_service()
#         event = event_service.get_event(execution_id)
#         if not event:
#             raise HTTPException(
#                 status_code=404,
#                 detail=f"Execution '{execution_id}' not found."
#             )
#         return event
#
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.exception(f"Error fetching execution data: {e}.")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Error fetching execution data: {e}."
#         )

# @router.post("/events", response_class=JSONResponse)
# async def create_event(
#     request: Request,
#     background_tasks: BackgroundTasks
# ):
#     try:
#         body = await request.json()
#         event_service = get_event_service()
#         result = event_service.emit(body)
#         try:
#             execution_id = result.get("execution_id") or body.get("execution_id")
#             if execution_id:
#                 # schedule async evaluator without blocking the request
#                 try:
#                     asyncio.create_task(evaluate_broker_for_execution(execution_id))
#                 except Exception:
#                     # fallback to background task for environments without running loop
#                     background_tasks.add_task(lambda eid=execution_id: _evaluate_broker_for_execution(eid))
#         except Exception:
#             pass
#         return result
#     except Exception as e:
#         logger.exception(f"Error creating event: {e}.")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Error creating event: {e}."
#         )


# @router.post("/agent/execute", response_class=JSONResponse)
# async def execute_agent(
#     request: Request,
#     path: str = None,
#     version: str = None,
#     input_payload: Dict[str, Any] = None,
#     sync_to_postgres: bool = True,
#     merge: bool = False
# ):
#     try:
#         logger.debug("=== EXECUTE_AGENT: Function entry ===")
#         logger.debug(f"EXECUTE_AGENT: Initial parameters - path={path}, version={version}, input_payload={input_payload}, sync_to_postgres={sync_to_postgres}, merge={merge}")
#
#         if not path:
#             try:
#                 body = await request.json()
#                 path = body.get("path", path)
#                 version = body.get("version", version)
#                 input_payload = body.get("input_payload", input_payload)
#                 sync_to_postgres = body.get("sync_to_postgres", sync_to_postgres)
#                 merge = body.get("merge", merge)
#                 logger.debug(f"EXECUTE_AGENT: Parameters from request body - path={path}, version={version}, input_payload={input_payload}, sync_to_postgres={sync_to_postgres}, merge={merge}")
#             except Exception as e:
#                 logger.debug(f"EXECUTE_AGENT: Failed to parse request body: {e}")
#                 pass
#
#         if not path:
#             logger.error("EXECUTE_AGENT: Missing required parameter path")
#             raise HTTPException(
#                 status_code=400,
#                 detail="Path is a required parameter."
#             )
#
#         logger.debug(f"EXECUTE_AGENT: Getting catalog service")
#         catalog_service = get_catalog_service()
#         if not version:
#             version = await catalog_service.get_latest_version(path)
#             logger.debug(f"EXECUTE_AGENT: Version not specified, using latest version: {version}")
#
#         logger.debug(f"EXECUTE_AGENT: Fetching entry for path={path}, version={version}")
#         entry = await catalog_service.fetch_entry(path, version)
#         if not entry:
#             logger.error(f"EXECUTE_AGENT: Playbook '{path}' with version '{version}' not found")
#             raise HTTPException(
#                 status_code=404,
#                 detail=f"Playbook '{path}' with version '{version}' not found."
#             )
#
#         logger.debug(f"EXECUTE_AGENT: Calling broker.execute_playbook_via_broker with playbook_path={path}, playbook_version={version}")
#         result = await asyncio.to_thread(
#             execute_playbook_via_broker,
#             entry.get("content"),
#             path,
#             version,
#             input_payload,
#             sync_to_postgres,
#             merge
#         )
#         logger.debug(f"EXECUTE_AGENT: broker.execute_playbook_via_broker returned result={result}")
#
#         logger.debug("=== EXECUTE_AGENT: Function exit ===")
#         return result
#
#     except Exception as e:
#         logger.exception(f"Error executing agent: {e}")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Error executing agent for playbooks '{path}' version '{version}': {e}."
#         )
#
# @router.post("/agent/execute-async", response_class=JSONResponse)
# async def execute_agent_async(
#     request: Request,
#     background_tasks: BackgroundTasks,
#     path: str = None,
#     version: str = None,
#     input_payload: Dict[str, Any] = None,
#     sync_to_postgres: bool = True,
#     merge: bool = False
# ):
#
#     try:
#         if not path:
#             try:
#                 body = await request.json()
#                 path = body.get("path", path)
#                 version = body.get("version", version)
#                 input_payload = body.get("input_payload", input_payload)
#                 sync_to_postgres = body.get("sync_to_postgres", sync_to_postgres)
#                 merge = body.get("merge", merge)
#             except:
#                 pass
#
#         if not path:
#             raise HTTPException(
#                 status_code=400,
#                 detail="Path is a required parameter."
#             )
#
#         catalog_service = get_catalog_service()
#
#         if not version:
#             version = await catalog_service.get_latest_version(path)
#             logger.info(f"Version not specified, using latest version: {version}")
#
#         entry = await catalog_service.fetch_entry(path, version)
#         if not entry:
#             raise HTTPException(
#                 status_code=404,
#                 detail=f"Playbook '{path}' with version '{version}' not found."
#             )
#
#         event_service = get_event_service()
#         initial_event_data = {
#             "event_type": "AgentExecutionRequested",
#             "status": "REQUESTED",
#             "meta": {
#                 "resource_path": path,
#                 "resource_version": version,
#             },
#             "result": input_payload,
#             "node_type": "playbooks",
#             "node_name": path
#         }
#
#         initial_event = event_service.emit(initial_event_data)
#
#         def execute_agent_task():
#             try:
#                 result = execute_playbook_via_broker(
#                     entry.get("content"),
#                     path,
#                     version,
#                     input_payload,
#                     sync_to_postgres,
#                     merge
#                 )
#                 event_id = initial_event.get("event_id")
#                 if result.get("status") == "success":
#                     execution_id = result.get("execution_id")
#                     update_event = {
#                         "event_id": event_id,
#                         "execution_id": execution_id,
#                         "event_type": "agent_execution_completed",
#                         "status": "COMPLETED",
#                         "result": result.get("result"),
#                         "meta": {
#                             "resource_path": path,
#                             "resource_version": version,
#                             "execution_id": execution_id
#                         },
#                         "node_type": "playbooks",
#                         "node_name": path
#                     }
#                     event_service.emit(update_event)
#                     logger.info(f"Event updated: {event_id} - agent_execution_completed - COMPLETED")
#                 else:
#                     error_event = {
#                         "event_id": event_id,
#                         "execution_id": event_id,
#                         "event_type": "agent_execution_error",
#                         "status": "ERROR",
#                         "error": result.get("error"),
#                         "result": {"error": result.get("error")},
#                         "meta": {
#                             "resource_path": path,
#                             "resource_version": version,
#                             "error": result.get("error")
#                         },
#                         "node_type": "playbooks",
#                         "node_name": path
#                     }
#                     event_service.emit(error_event)
#                     logger.info(f"Event updated: {event_id} - agent_execution_error - ERROR")
#             except Exception as e:
#                 logger.exception(f"Error in background agent execution: {e}.")
#                 event_id = initial_event.get("event_id")
#                 error_event = {
#                     "event_id": event_id,
#                     "execution_id": event_id,
#                     "event_type": "agent_execution_error",
#                     "status": "ERROR",
#                     "error": str(e),
#                     "result": {"error": str(e)},
#                     "meta": {
#                         "resource_path": path,
#                         "resource_version": version,
#                         "error": str(e)
#                     },
#                     "node_type": "playbooks",
#                     "node_name": path
#                 }
#                 event_service.emit(error_event)
#                 logger.info(f"Event updated: {event_id} - agent_execution_error - ERROR")
#
#         background_tasks.add_task(execute_agent_task)
#
#         return {
#             "status": "accepted",
#             "message": f"Agent execution started for playbooks '{path}' version '{version}'.",
#             "event_id": initial_event.get("event_id")
#         }
#
#     except Exception as e:
#         logger.exception(f"Error starting agent execution: {e}.")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Error starting agent execution for playbooks '{path}' version '{version}': {e}"
#         )


# @router.get("/dashboard/stats", response_class=JSONResponse)
# async def get_dashboard_stats():
#     """Get dashboard statistics"""
#     try:
#         return {
#             "total_executions": 0,
#             "successful_executions": 0,
#             "failed_executions": 0,
#             "total_playbooks": 0,
#             "active_workflows": 0
#         }
#     except Exception as e:
#         logger.error(f"Error getting dashboard stats: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
#
# @router.get("/dashboard/widgets", response_class=JSONResponse)
# async def get_dashboard_widgets():
#     """Get dashboard widgets"""
#     try:
#         return []
#     except Exception as e:
#         logger.error(f"Error getting dashboard widgets: {e}")
#         raise HTTPException(status_code=500, detail=str(e))

# @router.get("/playbooks", response_class=JSONResponse)
# async def get_playbooks():
#     """Get all playbooks (legacy endpoint)"""
#     return await get_catalog_playbooks()
#
# @router.get("/catalog/playbooks", response_class=JSONResponse)
# async def get_catalog_playbooks():
#     """Get all playbooks"""
#     try:
#         catalog_service = get_catalog_service()
#         entries = await catalog_service.list_entries('Playbook')
#
#         playbooks = []
#         for entry in entries:
#             meta = entry.get('meta', {})
#
#             description = ""
#             payload = entry.get('payload', {})
#
#             if isinstance(payload, str):
#                 try:
#                     payload_data = json.loads(payload)
#                     description = payload_data.get('description', '')
#                 except json.JSONDecodeError:
#                     description = ""
#             elif isinstance(payload, dict):
#                 description = payload.get('description', '')
#
#             if not description:
#                 description = meta.get('description', '')
#
#             playbook = {
#                 "id": entry.get('resource_path', ''),
#                 "name": entry.get('resource_path', '').split('/')[-1],
#                 "resource_type": entry.get('resource_type', ''),
#                 "resource_version": entry.get('resource_version', ''),
#                 "meta": entry.get('meta', ''),
#                 "timestamp": entry.get('timestamp', ''),
#                 "description": description,
#                 "created_at": entry.get('timestamp', ''),
#                 "updated_at": entry.get('timestamp', ''),
#                 "status": meta.get('status', 'active'),
#                 "tasks_count": meta.get('tasks_count', 0)
#             }
#             playbooks.append(playbook)
#
#         return playbooks
#     except Exception as e:
#         logger.error(f"Error getting playbooks: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
#
# @router.post("/catalog/playbooks", response_class=JSONResponse)
# async def create_catalog_playbook(request: Request):
#     """Create a new playbooks"""
#     try:
#         body = await request.json()
#         name = body.get("name", "New Playbook")
#         description = body.get("description", "")
#         status = body.get("status", "draft")
#
#         content = f"""# {name}
# name: "{name.lower().replace(' ', '-')}"
# description: "{description}"
# tasks:
#   - name: "sample-task"
#     type: "log"
#     config:
#       message: "Hello from NoETL!"
# """
#
#         catalog_service = get_catalog_service()
#         result = await catalog_service.register_resource(content, "playbooks")
#
#         playbook = {
#             "id": result.get("resource_path", ""),
#             "name": name,
#             "description": description,
#             "created_at": result.get("timestamp", ""),
#             "updated_at": result.get("timestamp", ""),
#             "status": status,
#             "tasks_count": 1,
#             "version": result.get("resource_version", "")
#         }
#
#         return playbook
#     except Exception as e:
#         logger.error(f"Error creating playbooks: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
#
# @router.post("/catalog/playbooks/validate", response_class=JSONResponse)
# async def validate_catalog_playbook(request: Request):
#     """Validate playbooks content"""
#     try:
#         body = await request.json()
#         content = body.get("content")
#
#         if not content:
#             raise HTTPException(
#                 status_code=400,
#                 detail="Content is required."
#             )
#
#         try:
#             yaml.safe_load(content)
#             return {"valid": True}
#         except Exception as yaml_error:
#             return {
#                 "valid": False,
#                 "errors": [str(yaml_error)]
#             }
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error validating playbooks: {e}")
#         raise HTTPException(status_code=500, detail=str(e))

@router.post("/executions/run", response_class=JSONResponse)
async def execute_playbook(request: Request):
    """Execute a playbooks"""
    try:
        logger.debug("=== EXECUTE_PLAYBOOK: Function entry ===")
        body = await request.json()
        playbook_id = body.get("playbook_id")
        parameters = body.get("parameters", {})
        
        logger.debug(f"EXECUTE_PLAYBOOK: Received request to execute playbook_id={playbook_id} with parameters={parameters}")
        
        if not playbook_id:
            logger.error("EXECUTE_PLAYBOOK: Missing required parameter playbook_id")
            raise HTTPException(
                status_code=400,
                detail="playbook_id is required."
            )
        
        logger.debug(f"EXECUTE_PLAYBOOK: Calling execute_agent for playbook_id={playbook_id}")
        result = await execute_agent(
            request=request,
            path=playbook_id,
            input_payload=parameters,
            sync_to_postgres=True,
            merge=False
        )
        logger.debug(f"EXECUTE_PLAYBOOK: execute_agent returned result={result}")
        
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
        logger.debug("=== EXECUTE_PLAYBOOK: Function exit ===")
        return execution
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing playbooks: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# @router.get("/catalog/playbooks/content", response_class=JSONResponse)
# async def get_catalog_playbook_content(playbook_id: str = Query(...)):
#     """Get playbook content"""
#     try:
#         logger.info(f"Received playbook_id: '{playbook_id}'")
#         if playbook_id.startswith("playbooks/"):
#             playbook_id = playbook_id[10:]
#             logger.info(f"Fixed playbook_id: '{playbook_id}'")
#
#         catalog_service = get_catalog_service()
#         latest_version = await catalog_service.get_latest_version(playbook_id)
#         logger.info(f"Latest version for '{playbook_id}': '{latest_version}'")
#
#         entry = await catalog_service.fetch_entry(playbook_id, latest_version)
#
#         if not entry:
#             raise HTTPException(
#                 status_code=404,
#                 detail=f"Playbook '{playbook_id}' not found."
#             )
#
#         return {"content": entry.get('content', '')}
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error getting playbook content: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
#
# @router.get("/catalog/playbook", response_class=JSONResponse)
# async def get_catalog_playbook(
#     playbook_id: str = Query(...),
#     # entry: Dict[str, Any] = Depends(get_playbook_entry_from_catalog)
# ):
#     """Get a single playbook by ID"""
#     try:
#         entry: Dict[str, Any] = await get_playbook_entry_from_catalog(playbook_id=playbook_id)
#         meta = entry.get('meta', {})
#         playbook_data = {
#             "id": entry.get('resource_path', ''),
#             "name": entry.get('resource_path', '').split('/')[-1],
#             "description": meta.get('description', ''),
#             "created_at": entry.get('timestamp', ''),
#             "updated_at": entry.get('timestamp', ''),
#             "status": meta.get('status', 'active'),
#             "tasks_count": meta.get('tasks_count', 0),
#             "version": entry.get('resource_version', '')
#         }
#         return playbook_data
#     except Exception as e:
#         logger.error(f"Error processing playbook entry: {e}")
#         raise HTTPException(status_code=500, detail="Error processing playbook data.")
#
# @router.put("/catalog/playbooks/{playbook_id:path}/content", response_class=JSONResponse)
# async def save_catalog_playbook_content(playbook_id: str, request: Request):
#     """Save playbooks content"""
#     try:
#         logger.info(f"Received playbook_id for save: '{playbook_id}'")
#         if playbook_id.startswith("playbooks/"):
#             playbook_id = playbook_id[10:]
#             logger.info(f"Fixed playbook_id for save: '{playbook_id}'")
#
#         body = await request.json()
#         content = body.get("content")
#
#         if not content:
#             raise HTTPException(
#                 status_code=400,
#                 detail="Content is required."
#             )
#         catalog_service = get_catalog_service()
#         result = await catalog_service.register_resource(content, "playbooks")
#
#         return {
#             "status": "success",
#             "message": f"Playbook '{playbook_id}' content updated.",
#             "resource_path": result.get("resource_path"),
#             "resource_version": result.get("resource_version")
#         }
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error saving playbooks content: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
#
# @router.get("/catalog/widgets", response_class=JSONResponse)
# async def get_catalog_widgets():
#     """Get catalog visualization widgets"""
#     try:
#         playbook_count = 0
#         active_count = 0
#         draft_count = 0
#
#         try:
#             with get_db_connection() as conn:
#                 with conn.cursor() as cursor:
#                     cursor.execute(
#                         "SELECT COUNT(DISTINCT resource_path) FROM catalog WHERE resource_type = 'widget'"
#                     )
#                     playbook_count = cursor.fetchone()[0]
#
#                     cursor.execute(
#                         """
#                         SELECT meta FROM catalog
#                         WHERE resource_type = 'widget'
#                         """
#                     )
#                     results = cursor.fetchall()
#
#                     for row in results:
#                         meta_str = row[0]
#                         if meta_str:
#                             try:
#                                 meta = json.loads(meta_str) if isinstance(meta_str, str) else meta_str
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
#             logger.warning(f"Error getting catalog stats from database: {db_error}")
#             playbook_count = 0
#
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

# @router.get("/executions", response_class=JSONResponse)
# async def get_executions():
#     """Get all executions"""
#     try:
#         event_service = get_event_service()
#         executions = event_service.get_all_executions()
#         return executions
#     except Exception as e:
#         logger.error(f"Error getting executions: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
#
# @router.get("/executions/{execution_id}", response_class=JSONResponse)
# async def get_execution(execution_id: str):
#     try:
#         event_service = get_event_service()
#         events = event_service.get_events_by_execution_id(execution_id)
#
#         if not events:
#             raise HTTPException(
#                 status_code=404,
#                 detail=f"Execution '{execution_id}' not found."
#             )
#
#         latest_event = None
#         for event in events.get("events", []):
#             if not latest_event or (event.get("timestamp", "") > latest_event.get("timestamp", "")):
#                 latest_event = event
#
#         if not latest_event:
#             raise HTTPException(
#                 status_code=404,
#                 detail=f"No events found for execution '{execution_id}'."
#             )
#
#         metadata = latest_event.get("metadata", {})
#         input_context = latest_event.get("input_context", {})
#         output_result = latest_event.get("output_result", {})
#
#         playbook_id = metadata.get('resource_path', input_context.get('path', ''))
#         playbook_name = playbook_id.split('/')[-1] if playbook_id else 'Unknown'
#
#         raw_status = latest_event.get("status", "")
#         status = event_service._normalize_status(raw_status)
#
#         timestamps = [event.get("timestamp", "") for event in events.get("events", []) if event.get("timestamp")]
#         timestamps.sort()
#
#         start_time = timestamps[0] if timestamps else None
#         end_time = timestamps[-1] if timestamps and status in ['completed', 'failed'] else None
#
#         duration = None
#         if start_time and end_time:
#             try:
#                 start_dt = datetime.fromisoformat(start_time)
#                 end_dt = datetime.fromisoformat(end_time)
#                 duration = (end_dt - start_dt).total_seconds()
#             except Exception as e:
#                 logger.error(f"Error calculating duration: {e}")
#
#         if status in ['completed', 'failed']:
#             progress = 100
#         elif status == 'running':
#             normalized_statuses = [event_service._normalize_status(e.get('status')) for e in events.get('events', [])]
#             total = len(normalized_statuses)
#             done = sum(1 for s in normalized_statuses if s in {'completed', 'failed'})
#             progress = int((done / total) * 100) if total else 0
#         else:
#             progress = 0
#
#         execution_data = {
#             "id": execution_id,
#             "playbook_id": playbook_id,
#             "playbook_name": playbook_name,
#             "status": status,
#             "start_time": start_time,
#             "end_time": end_time,
#             "duration": duration,
#             "progress": progress,
#             "result": output_result,
#             "error": latest_event.get("error"),
#             "events": events.get("events", [])
#         }
#
#         return execution_data
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error getting execution: {e}")
#         raise HTTPException(status_code=500, detail=str(e))

# @router.get("/health", response_class=JSONResponse)
# async def api_health():
#     """API health check endpoint"""
#     return {"status": "ok"}

# @router.post("/worker/pool/register", response_class=JSONResponse)
# async def register_worker_pool(request: Request):
#     """
#     Register or update a worker pool in the runtime registry.
#     Body:
#       { name, runtime, base_url, status, capacity?, labels?, pid?, hostname?, meta? }
#     """
#     try:
#         body = await request.json()
#         name = (body.get("name") or "").strip()
#         runtime = (body.get("runtime") or "").strip().lower()
#         base_url = (body.get("base_url") or "").strip()
#         status = (body.get("status") or "ready").strip().lower()
#         capacity = body.get("capacity")
#         labels = body.get("labels")
#         pid = body.get("pid")
#         hostname = body.get("hostname")
#         meta = body.get("meta") or {}
#         if not name or not runtime or not base_url:
#             raise HTTPException(status_code=400, detail="name, runtime, and base_url are required")
#
#         import datetime as _dt
#         try:
#             from noetl.common import get_snowflake_id
#             rid = get_snowflake_id()
#         except Exception:
#             rid = int(_dt.datetime.now().timestamp() * 1000)
#
#         payload_runtime = {
#             "type": runtime,
#             "pid": pid,
#             "hostname": hostname,
#             **({} if not isinstance(meta, dict) else meta),
#         }
#
#         labels_json = json.dumps(labels) if labels is not None else None
#         runtime_json = json.dumps(payload_runtime)
#
#         from noetl.common import get_db_connection
#         with get_db_connection() as conn:
#             with conn.cursor() as cursor:
#                 cursor.execute(
#                     f"""
#                     INSERT INTO runtime (runtime_id, name, component_type, base_url, status, labels, capacity, runtime, last_heartbeat, created_at, updated_at)
#                     VALUES (%s, %s, 'worker_pool', %s, %s, %s::jsonb, %s, %s::jsonb, now(), now(), now())
#                     ON CONFLICT (component_type, name)
#                     DO UPDATE SET
#                         base_url = EXCLUDED.base_url,
#                         status = EXCLUDED.status,
#                         labels = EXCLUDED.labels,
#                         capacity = EXCLUDED.capacity,
#                         runtime = EXCLUDED.runtime,
#                         last_heartbeat = now(),
#                         updated_at = now()
#                     RETURNING runtime_id
#                     """,
#                     (rid, name, base_url, status, labels_json, capacity, runtime_json)
#                 )
#                 row = cursor.fetchone()
#                 conn.commit()
#         return {"status": "ok", "name": name, "runtime": runtime, "runtime_id": row[0] if row else rid}
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.exception(f"Error registering worker pool: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
#
# @router.delete("/worker/pool/deregister", response_class=JSONResponse)
# async def deregister_worker_pool(request: Request):
#     """
#     Deregister a worker pool by name (marks as offline).
#     Body: { name }
#     """
#     try:
#         body = await request.json()
#         name = (body.get("name") or "").strip()
#         if not name:
#             raise HTTPException(status_code=400, detail="name is required")
#         from noetl.common import get_db_connection
#         with get_db_connection() as conn:
#             with conn.cursor() as cursor:
#                 cursor.execute(
#                     """
#                     UPDATE runtime
#                     SET status = 'offline', updated_at = now()
#                     WHERE component_type = 'worker_pool' AND name = %s
#                     """,
#                     (name,)
#                 )
#                 conn.commit()
#         return {"status": "ok", "name": name}
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.exception(f"Error deregistering worker pool: {e}")
#         raise HTTPException(status_code=500, detail=str(e))

# -------------------- Queue API --------------------
# @router.post("/queue/enqueue", response_class=JSONResponse)
# async def enqueue_job(request: Request):
#     """Enqueue a job into the noetl.queue table.
#     Body: { execution_id, node_id, action, input_context?, priority?, max_attempts?, available_at? }
#     """
#     try:
#         body = await request.json()
#         execution_id = body.get("execution_id")
#         node_id = body.get("node_id")
#         action = body.get("action")
#         input_context = body.get("input_context", {})
#         priority = int(body.get("priority", 0))
#         max_attempts = int(body.get("max_attempts", 5))
#         available_at = body.get("available_at")
#
#         if not execution_id or not node_id or not action:
#             raise HTTPException(status_code=400, detail="execution_id, node_id and action are required")
#
#         with get_db_connection() as conn:
#             with conn.cursor() as cur:
#                 cur.execute(
#                     """
#                     INSERT INTO noetl.queue (execution_id, node_id, action, input_context, priority, max_attempts, available_at)
#                     VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)
#                     RETURNING id
#                     """,
#                     (execution_id, node_id, action, json.dumps(input_context), priority, max_attempts, available_at)
#                 )
#                 row = cur.fetchone()
#                 conn.commit()
#         return {"status": "ok", "id": row[0]}
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.exception(f"Error enqueueing job: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
#
#
# @router.post("/queue/lease", response_class=JSONResponse)
# async def lease_job(request: Request):
#     """Atomically lease a queued job for a worker.
#     Body: { worker_id, lease_seconds? }
#     Returns queued job or {status: 'empty'} when nothing available.
#     """
#     try:
#         body = await request.json()
#         worker_id = body.get("worker_id")
#         lease_seconds = int(body.get("lease_seconds", 60))
#         if not worker_id:
#             raise HTTPException(status_code=400, detail="worker_id is required")
#
#         with get_db_connection() as conn:
#             # return dict-like row for JSON friendliness
#             with conn.cursor(row_factory=dict_row) as cur:
#                 cur.execute(
#                     """
#                     WITH cte AS (
#                       SELECT id FROM noetl.queue
#                       WHERE status='queued' AND available_at <= now()
#                       ORDER BY priority DESC, id
#                       FOR UPDATE SKIP LOCKED
#                       LIMIT 1
#                     )
#                     UPDATE noetl.queue q
#                     SET status='leased',
#                         worker_id=%s,
#                         lease_until=now() + (%s || ' seconds')::interval,
#                         last_heartbeat=now(),
#                         attempts = q.attempts + 1
#                     FROM cte
#                     WHERE q.id = cte.id
#                     RETURNING q.*;
#                     """,
#                     (worker_id, str(lease_seconds))
#                 )
#                 row = cur.fetchone()
#                 conn.commit()
#
#         if not row:
#             return {"status": "empty"}
#
#         # ensure JSON serializable
#         if row.get("input_context") is None:
#             row["input_context"] = {}
#         return {"status": "ok", "job": row}
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.exception(f"Error leasing job: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
#
#
# @router.post("/queue/{job_id}/complete", response_class=JSONResponse)
# async def complete_job(job_id: int):
#     """Mark a job completed."""
#     try:
#         with get_db_connection() as conn:
#             with conn.cursor() as cur:
#                 cur.execute("UPDATE noetl.queue SET status='done', lease_until = NULL, updated_at = now() WHERE id = %s RETURNING id", (job_id,))
#                 row = cur.fetchone()
#                 conn.commit()
#         if not row:
#             raise HTTPException(status_code=404, detail="job not found")
#         return {"status": "ok", "id": job_id}
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.exception(f"Error completing job {job_id}: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
#
#
# @router.post("/queue/{job_id}/fail", response_class=JSONResponse)
# async def fail_job(job_id: int, request: Request):
#     """Mark job failed; optionally reschedule if attempts < max_attempts.
#     Body: { retry_delay_seconds? }
#     """
#     try:
#         body = await request.json()
#         retry_delay = int(body.get("retry_delay_seconds", 60))
#         with get_db_connection() as conn:
#             with conn.cursor(row_factory=dict_row) as cur:
#                 cur.execute("SELECT attempts, max_attempts FROM noetl.queue WHERE id = %s", (job_id,))
#                 row = cur.fetchone()
#                 if not row:
#                     raise HTTPException(status_code=404, detail="job not found")
#                 attempts = row.get("attempts", 0)
#                 max_attempts = row.get("max_attempts", 5)
#
#                 if attempts >= max_attempts:
#                     cur.execute("UPDATE noetl.queue SET status='dead', updated_at = now() WHERE id = %s RETURNING id", (job_id,))
#                 else:
#                     cur.execute("UPDATE noetl.queue SET status='queued', available_at = now() + (%s || ' seconds')::interval, updated_at = now() WHERE id = %s RETURNING id", (str(retry_delay), job_id))
#                 updated = cur.fetchone()
#                 conn.commit()
#         return {"status": "ok", "id": job_id}
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.exception(f"Error failing job {job_id}: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
#
#
# @router.post("/queue/{job_id}/heartbeat", response_class=JSONResponse)
# async def heartbeat_job(job_id: int, request: Request):
#     """Update heartbeat and optionally extend lease_until.
#     Body: { worker_id?, extend_seconds? }
#     """
#     try:
#         body = await request.json()
#         worker_id = body.get("worker_id")
#         extend = body.get("extend_seconds")
#         with get_db_connection() as conn:
#             with conn.cursor() as cur:
#                 if extend:
#                     cur.execute("UPDATE noetl.queue SET last_heartbeat = now(), lease_until = now() + (%s || ' seconds')::interval WHERE id = %s RETURNING id", (str(int(extend)), job_id))
#                 else:
#                     cur.execute("UPDATE noetl.queue SET last_heartbeat = now() WHERE id = %s RETURNING id", (job_id,))
#                 row = cur.fetchone()
#                 conn.commit()
#         if not row:
#             raise HTTPException(status_code=404, detail="job not found")
#         return {"status": "ok", "id": job_id}
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.exception(f"Error heartbeating job {job_id}: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
#
#
# @router.get("/queue", response_class=JSONResponse)
# async def list_queue(status: str = None, execution_id: str = None, worker_id: str = None, limit: int = 100):
#     try:
#         filters = []
#         params: list[Any] = []
#         if status:
#             filters.append("status = %s")
#             params.append(status)
#         if execution_id:
#             filters.append("execution_id = %s")
#             params.append(execution_id)
#         if worker_id:
#             filters.append("worker_id = %s")
#             params.append(worker_id)
#         where = f"WHERE {' AND '.join(filters)}" if filters else ''
#         with get_db_connection() as conn:
#             with conn.cursor(row_factory=dict_row) as cur:
#                 cur.execute(f"SELECT * FROM noetl.queue {where} ORDER BY priority DESC, id LIMIT %s", params + [limit])
#                 rows = cur.fetchall()
#         for r in rows:
#             if r.get('input_context') is None:
#                 r['input_context'] = {}
#         return {"status": "ok", "items": rows}
#     except Exception as e:
#         logger.exception(f"Error listing queue: {e}")
#         raise HTTPException(status_code=500, detail=str(e))
