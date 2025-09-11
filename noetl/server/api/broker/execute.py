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
                workflow_steps = pb.get('workflow', [])
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
