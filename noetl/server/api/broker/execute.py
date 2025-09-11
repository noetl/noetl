"""
Kickoff helpers for server-side playbook execution via the event-sourced path.

Moved from legacy noetl/broker.py
"""

from __future__ import annotations

import os
import uuid
import datetime
from typing import Dict, Any, Optional

from noetl.core.common import deep_merge
from noetl.worker.plugin import report_event
from noetl.core.logger import setup_logger
from .broker import Broker

logger = setup_logger(__name__, include_location=True)


def execute_playbook_via_broker(
    playbook_content: str,
    playbook_path: str,
    playbook_version: str,
    input_payload: Optional[Dict[str, Any]] = None,
    sync_to_postgres: bool = True,
    merge: bool = False,
    parent_execution_id: Optional[str] = None,
    parent_event_id: Optional[str] = None,
    parent_step: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Event-sourced kickoff of a playbook execution without directly using Worker.
    - Generates an execution_id.
    - Prepares merged workload context (playbook workload +/- input_payload).
    - Emits an execution_start event to the server API.
    - Returns immediately with the execution_id; further step evaluation is
      handled by the event-driven broker path.
    """
    logger.debug("=== BROKER.EXECUTE_PLAYBOOK_VIA_BROKER: Function entry ===")
    logger.debug(
        f"BROKER.EXECUTE_PLAYBOOK_VIA_BROKER: Parameters - playbook_path={playbook_path}, playbook_version={playbook_version}, input_payload={input_payload}, sync_to_postgres={sync_to_postgres}, merge={merge}"
    )

    try:
        # Create execution ID (prefer snowflake if available)
        try:
            from noetl.core.common import get_snowflake_id_str as _snow_id  # type: ignore
            execution_id = _snow_id()
        except Exception:
            try:
                from noetl.core.common import get_snowflake_id as _snow
                execution_id = str(_snow())
            except Exception:
                execution_id = str(uuid.uuid4())

        # Load workload from playbook content (best-effort)
        try:
            import yaml
            pb = yaml.safe_load(playbook_content) or {}
            base_workload = pb.get('workload', {}) if isinstance(pb, dict) else {}
        except Exception:
            base_workload = {}

        if input_payload:
            if merge:
                merged_workload = deep_merge(base_workload, input_payload)
            else:
                merged_workload = {**base_workload, **input_payload}
        else:
            merged_workload = base_workload

        # Best-effort: persist workload row immediately so evaluator can read it
        try:
            from noetl.core.common import get_async_db_connection as _get_async_db_connection
            from noetl.database import sqlcmd as _sqlcmd
            import asyncio as _asyncio
            import json as _json

            async def _persist_workload_row(_exec_id, _path, _version, _workload):
                try:
                    payload = {
                        'path': _path,
                        'version': _version,
                        'workload': _workload or {},
                    }
                    data = _json.dumps(payload)
                    async with _get_async_db_connection() as _conn:
                        async with _conn.cursor() as _cur:
                            try:
                                await _cur.execute(_sqlcmd.WORKLOAD_INSERT_POSTGRES, (_exec_id, data))
                            except Exception:
                                try:
                                    await _cur.execute(_sqlcmd.WORKLOAD_INSERT_DUCKDB, (_exec_id, data))
                                except Exception:
                                    # Try update as last resort for duckdb
                                    try:
                                        await _cur.execute(_sqlcmd.WORKLOAD_UPDATE_DUCKDB, (data, _exec_id))
                                    except Exception:
                                        pass
                            try:
                                await _conn.commit()
                            except Exception:
                                pass
                except Exception:
                    logger.debug("EXECUTE: Failed to persist workload row (best-effort)", exc_info=True)

            try:
                _asyncio.run(_persist_workload_row(execution_id, playbook_path, playbook_version, merged_workload))
            except RuntimeError:
                loop = _asyncio.get_event_loop()
                loop.create_task(_persist_workload_row(execution_id, playbook_path, playbook_version, merged_workload))
        except Exception:
            logger.debug("EXECUTE: Skipped workload persistence", exc_info=True)

        # Initialize broker and populate workflow data
        try:
            # Create a mock agent for the broker
            class MockAgent:
                def __init__(self, playbook_path):
                    self.playbook_path = playbook_path
                    self.execution_id = execution_id

            broker = Broker(MockAgent(playbook_path))

            # Populate default tables if specified in playbook
            if pb and isinstance(pb, dict):
                # Extract default tables configuration
                default_tables_config = {}

                # Check if playbook has workflow steps with table configurations
                workflow_steps = (pb.get('workflow') or pb.get('steps') or [])
                if workflow_steps:
                    broker.workflow(workflow_steps, execution_id=execution_id, playbook_path=playbook_path)
                    logger.info(f"Populated workflow with {len(workflow_steps)} steps")

                # Look for default tables in workload or metadata
                if 'default_tables' in pb:
                    default_tables_config = pb['default_tables']
                elif 'tables' in base_workload:
                    default_tables_config = base_workload['tables']

                if default_tables_config:
                    broker.default_tables(default_tables_config)
                    logger.info(f"Populated default tables: {list(default_tables_config.keys())}")

                # Set up transitions between workflow steps
                for i, step in enumerate(workflow_steps):
                    step_name = step.get('step', f'step_{i}')
                    next_steps = step.get('next', [])
                    for next_step in next_steps:
                        if isinstance(next_step, dict) and 'step' in next_step:
                            next_step_name = next_step['step']
                            condition = next_step.get('when')
                            broker.transition(step_name, next_step_name, condition)
                        elif isinstance(next_step, str):
                            broker.transition(step_name, next_step)

            logger.info(f"Broker initialized and populated for execution {execution_id}")

        except Exception as e:
            logger.warning(f"Failed to initialize broker for execution {execution_id}: {e}")

        # Best-effort: persist workflow/transition config directly if HTTP event reporting is disabled
        try:
            from noetl.core.common import get_async_db_connection as _get_async_db_connection
            from noetl.database import sqlcmd as _sqlcmd
            import asyncio as _asyncio
            import json as _json

            async def _persist_workflow(_steps, _exec_id, _pb_path):
                try:
                    async with _get_async_db_connection() as conn:
                        async with conn.cursor() as cur:
                            # Transitions
                            for st in _steps or []:
                                try:
                                    from_step = st.get("step") or st.get("name")
                                    next_list = st.get("next") or []
                                    for nx in next_list:
                                        try:
                                            if isinstance(nx, dict):
                                                to_step = nx.get("step") or nx.get("name")
                                                condition = nx.get("when") or nx.get("condition")
                                                with_params = nx.get("with") or {}
                                            else:
                                                to_step = str(nx)
                                                condition = None
                                                with_params = {}
                                            if from_step and to_step:
                                                try:
                                                    await cur.execute(
                                                        _sqlcmd.TRANSITION_INSERT_POSTGRES,
                                                        (
                                                            _exec_id,
                                                            from_step,
                                                            to_step,
                                                            condition,
                                                            _json.dumps(with_params) if with_params is not None else None,
                                                        ),
                                                    )
                                                except Exception:
                                                    try:
                                                        await cur.execute(
                                                            _sqlcmd.TRANSITION_INSERT_DUCKDB,
                                                            (
                                                                _exec_id,
                                                                from_step,
                                                                to_step,
                                                                condition,
                                                                _json.dumps(with_params) if with_params is not None else None,
                                                            ),
                                                        )
                                                    except Exception:
                                                        logger.debug("EXECUTE: Failed to insert transition (direct)", exc_info=True)
                                        except Exception:
                                            logger.debug("EXECUTE: Error processing next transition (direct)", exc_info=True)
                                except Exception:
                                    logger.debug("EXECUTE: Error processing step transitions (direct)", exc_info=True)

                            # Workflow rows
                            for st in _steps or []:
                                try:
                                    step_name = st.get("step") or st.get("name") or ""
                                    step_type = st.get("type") or st.get("kind") or st.get("task_type") or ""
                                    desc = st.get("desc") or st.get("description") or ""
                                    task_ref = st.get("task") or st.get("action") or st.get("name") or ""
                                    raw = _json.dumps(st)
                                    vals6 = (
                                        _exec_id,
                                        _pb_path or "",
                                        step_name,
                                        step_type,
                                        desc,
                                        raw,
                                    )
                                    try:
                                        await cur.execute(_sqlcmd.WORKFLOW_INSERT_POSTGRES, vals6)
                                    except Exception:
                                        try:
                                            await cur.execute(_sqlcmd.WORKFLOW_INSERT_DUCKDB, vals6)
                                        except Exception:
                                            logger.debug("EXECUTE: Failed to insert workflow row (direct)", exc_info=True)
                                except Exception:
                                    logger.debug("EXECUTE: Error inserting workflow row (direct)", exc_info=True)

                            # Workbook rows (subset)
                            for st in _steps or []:
                                try:
                                    st_type = (st.get("type") or "").lower()
                                    if st_type != "workbook":
                                        continue
                                    step_name = st.get("step") or st.get("name") or ""
                                    task_name = st.get("task") or st.get("name") or ""
                                    raw = _json.dumps(st)
                                    vals5 = (
                                        _exec_id,
                                        _pb_path or "",
                                        step_name,
                                        task_name,
                                        raw,
                                    )
                                    try:
                                        await cur.execute(_sqlcmd.WORKBOOK_INSERT_POSTGRES, vals5)
                                    except Exception:
                                        try:
                                            await cur.execute(_sqlcmd.WORKBOOK_INSERT_DUCKDB, vals5)
                                        except Exception:
                                            logger.debug("EXECUTE: Failed to insert workbook row (direct)", exc_info=True)
                                except Exception:
                                    logger.debug("EXECUTE: Error inserting workbook row (direct)", exc_info=True)
                            try:
                                await conn.commit()
                            except Exception:
                                pass
                except Exception:
                    logger.debug("EXECUTE: Direct workflow persistence failed", exc_info=True)

            # Run direct persistence as a best-effort backup regardless of HTTP reporting.
            # This keeps transition/workflow tables updated even if the API endpoint is unreachable
            # or disabled. Duplicate inserts are tolerated by catching exceptions.
            _workflow_steps = (pb.get('workflow') or pb.get('steps') or []) if isinstance(pb, dict) else []
            if _workflow_steps:
                try:
                    _asyncio.run(_persist_workflow(_workflow_steps, execution_id, playbook_path))
                except RuntimeError:
                    # If already in loop
                    loop = _asyncio.get_event_loop()
                    loop.create_task(_persist_workflow(_workflow_steps, execution_id, playbook_path))
        except Exception:
            logger.debug("EXECUTE: Skipped direct workflow persistence", exc_info=True)

        # Emit execution_start directly via EventService to avoid HTTP loop/timeout
        try:
            ctx = {
                "path": playbook_path,
                "version": playbook_version,
                "workload": merged_workload,
            }
            try:
                from noetl.server.api.event import get_event_service
                es = get_event_service()
                import asyncio as _asyncio
                if _asyncio.get_event_loop().is_running():
                    # within async server context
                    payload = {
                        'event_type': 'execution_start',
                        'execution_id': execution_id,
                        'status': 'IN_PROGRESS',
                        'timestamp': datetime.datetime.now().isoformat(),
                        'node_type': 'playbook',
                        'node_name': playbook_path.split('/')[-1] if playbook_path else 'playbook',
                        'context': ctx,
                        'meta': {'playbook_path': playbook_path, 'resource_path': playbook_path, 'resource_version': playbook_version, 'parent_execution_id': parent_execution_id, 'parent_step': parent_step},
                    }
                    if parent_event_id:
                        payload['parent_event_id'] = parent_event_id
                    _asyncio.create_task(es.emit(payload))
                else:
                    # best-effort synchronous run
                    payload = {
                        'event_type': 'execution_start',
                        'execution_id': execution_id,
                        'status': 'IN_PROGRESS',
                        'timestamp': datetime.datetime.now().isoformat(),
                        'node_type': 'playbook',
                        'node_name': playbook_path.split('/')[-1] if playbook_path else 'playbook',
                        'context': ctx,
                        'meta': {'playbook_path': playbook_path, 'resource_path': playbook_path, 'resource_version': playbook_version, 'parent_execution_id': parent_execution_id, 'parent_step': parent_step},
                    }
                    if parent_event_id:
                        payload['parent_event_id'] = parent_event_id
                    _asyncio.run(es.emit(payload))
            except Exception:
                # Fallback to HTTP if direct emit fails
                server_url = os.environ.get("NOETL_SERVER_URL", "http://localhost:8082").rstrip('/')
                if not server_url.endswith('/api'):
                    server_url = server_url + '/api'
                report_event({
                    'event_type': 'execution_start',
                    'execution_id': execution_id,
                    'status': 'IN_PROGRESS',
                    'timestamp': datetime.datetime.now().isoformat(),
                    'node_type': 'playbook',
                    'node_name': playbook_path.split('/')[-1] if playbook_path else 'playbook',
                    'context': ctx,
                    'meta': {'playbook_path': playbook_path, 'resource_path': playbook_path, 'resource_version': playbook_version},
                }, server_url)
        except Exception as e_evt:
            logger.warning(f"BROKER.EXECUTE_PLAYBOOK_VIA_BROKER: Failed to persist execution_start event: {e_evt}")

        result = {
            "status": "success",
            "message": f"Execution accepted for playbooks '{playbook_path}' version '{playbook_version}'.",
            "result": {"status": "queued"},
            "execution_id": execution_id,
            "export_path": None,
        }
        # Kick off broker evaluation for this execution id
        logger.info(f"BROKER.EXECUTE_PLAYBOOK_VIA_BROKER: Attempting to start broker evaluation for execution_id={execution_id}")
        try:
            from noetl.server.api.event import evaluate_broker_for_execution
            import asyncio as _asyncio

            logger.info(f"BROKER.EXECUTE_PLAYBOOK_VIA_BROKER: evaluate_broker_for_execution imported successfully")

            if _asyncio.get_event_loop().is_running():
                logger.info(f"BROKER.EXECUTE_PLAYBOOK_VIA_BROKER: Running in async context, creating task for execution_id={execution_id}")
                task = _asyncio.create_task(evaluate_broker_for_execution(execution_id))
                logger.info(f"BROKER.EXECUTE_PLAYBOOK_VIA_BROKER: Task created: {task}")
            else:
                logger.info(f"BROKER.EXECUTE_PLAYBOOK_VIA_BROKER: Running in sync context, using asyncio.run for execution_id={execution_id}")
                _asyncio.run(evaluate_broker_for_execution(execution_id))

            logger.info(f"BROKER.EXECUTE_PLAYBOOK_VIA_BROKER: Broker evaluation initiated successfully for execution_id={execution_id}")

        except Exception as _ev:
            logger.error(f"BROKER.EXECUTE_PLAYBOOK_VIA_BROKER: Failed to start broker evaluation for execution_id={execution_id}: {_ev}")
            import traceback
            logger.error(f"BROKER.EXECUTE_PLAYBOOK_VIA_BROKER: Traceback: {traceback.format_exc()}")

        logger.debug(
            f"BROKER.EXECUTE_PLAYBOOK_VIA_BROKER: Returning accepted result for execution_id={execution_id}"
        )
        logger.debug("=== BROKER.EXECUTE_PLAYBOOK_VIA_BROKER: Function exit ===")
        return result
    except Exception as e:
        logger.exception(
            f"BROKER.EXECUTE_PLAYBOOK_VIA_BROKER: Error preparing execution for playbooks '{playbook_path}' version '{playbook_version}': {e}."
        )
        return {
            "status": "error",
            "message": f"Error executing agent for playbooks '{playbook_path}' version '{playbook_version}': {e}.",
            "error": str(e),
        }
