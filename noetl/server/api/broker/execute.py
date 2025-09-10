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
from noetl.job import report_event
from noetl.core.logger import setup_logger

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

        # Emit execution_start directly via EventService to avoid HTTP loop/timeout
        try:
            ctx = {
                "path": playbook_path,
                "version": playbook_version,
                "workload": merged_workload,
            }
            try:
                from noetl.api.event import get_event_service
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
        try:
            from noetl.api.event import evaluate_broker_for_execution
            import asyncio as _asyncio
            if _asyncio.get_event_loop().is_running():
                _asyncio.create_task(evaluate_broker_for_execution(execution_id))
            else:
                _asyncio.run(evaluate_broker_for_execution(execution_id))
        except Exception as _ev:
            logger.warning(f"BROKER.EXECUTE_PLAYBOOK_VIA_BROKER: Failed to start broker evaluation: {_ev}")
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
