"""
Gateway tool executor for NoETL jobs.

Handles communication between playbooks and the API gateway.
Abstracts messaging infrastructure (NATS) from playbook authors.
"""

import uuid
import datetime
import os
import json
from typing import Dict, Any, Optional, Callable
from jinja2 import Environment

from noetl.core.dsl.render import render_template
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)

# NATS client for publishing callbacks
_nats_client = None


async def _get_nats_client():
    """Get or create NATS client singleton."""
    global _nats_client
    if _nats_client is None or _nats_client.is_closed:
        import nats
        nats_url = os.getenv("NATS_URL", "nats://nats.nats.svc.cluster.local:4222")
        logger.info(f"GATEWAY: Connecting to NATS at {nats_url}")
        _nats_client = await nats.connect(nats_url)
    return _nats_client


async def _publish_callback(subject: str, payload: Dict[str, Any]) -> bool:
    """Publish callback message to NATS."""
    try:
        nc = await _get_nats_client()
        message = json.dumps(payload).encode()
        await nc.publish(subject, message)
        await nc.flush()
        logger.debug(f"GATEWAY: Published callback to {subject}")
        return True
    except Exception as e:
        logger.error(f"GATEWAY: Failed to publish callback: {e}")
        return False


async def execute_gateway_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Dict[str, Any],
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a gateway task.

    Actions:
        - callback: Send result back to gateway for async request-response
        - wait: Pause and wait for external input (future)
        - notify: Send notification event (future)

    Args:
        task_config: The task configuration containing:
            - action: "callback" | "wait" | "notify"
            - data: Data to send (for callback)
            - event: Event name (for wait/notify)
            - timeout: Timeout in seconds (for wait)
        context: The execution context (includes workload, job, step results)
        jinja_env: The Jinja2 environment for template rendering
        task_with: Rendered parameters
        log_event_callback: Optional callback for logging events

    Returns:
        A dictionary with task result
    """
    task_id = str(uuid.uuid4())
    task_name = task_config.get('task', 'gateway_task')
    start_time = datetime.datetime.now()

    logger.debug(f"GATEWAY.EXECUTE: Entry - action={task_config.get('action')} task_config={task_config}")

    try:
        action = task_config.get('action', 'callback')

        if action == 'callback':
            return await _execute_callback(task_id, task_name, start_time, task_config, context, jinja_env, task_with)
        elif action == 'wait':
            return await _execute_wait(task_id, task_name, start_time, task_config, context, jinja_env, task_with)
        elif action == 'notify':
            return await _execute_notify(task_id, task_name, start_time, task_config, context, jinja_env, task_with)
        else:
            raise ValueError(f"Unknown gateway action: {action}")

    except Exception as e:
        error_msg = str(e)
        logger.error(f"GATEWAY.EXECUTE: Exception - {error_msg}", exc_info=True)
        return {
            'id': task_id,
            'status': 'error',
            'error': error_msg
        }


async def _execute_callback(
    task_id: str,
    task_name: str,
    start_time: datetime.datetime,
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Execute callback action - send result back to gateway.

    The callback subject is obtained from workload.callback_subject (set by gateway).
    Playbook authors don't need to know about NATS - they just specify the data.
    """
    workload = context.get('workload', {})
    job = context.get('job', {})

    # Get callback subject - set by gateway when starting the playbook
    callback_subject = workload.get('callback_subject')
    if not callback_subject:
        logger.warning("GATEWAY.CALLBACK: No callback_subject in workload, checking for callback_url")
        # Fall back to HTTP callback if no NATS subject
        callback_url = workload.get('callback_url')
        if callback_url:
            return await _execute_http_callback(task_id, task_name, start_time, task_config, context, jinja_env, task_with, callback_url)
        else:
            logger.info("GATEWAY.CALLBACK: No callback configured, skipping")
            return {
                'id': task_id,
                'status': 'success',
                'data': {'skipped': True, 'reason': 'no_callback_configured'}
            }

    # Get request ID for correlation
    request_id = workload.get('request_id', '')
    execution_id = job.get('execution_id', '')

    # Render the data to send
    raw_data = task_config.get('data', {})
    data = render_template(jinja_env, raw_data, context)

    # Get step name for tracking
    step_name = task_config.get('step', context.get('current_step', 'unknown'))

    # Build callback payload
    import socket
    worker_hostname = socket.gethostname()
    payload = {
        'request_id': request_id,
        'execution_id': execution_id,
        'step': step_name,
        'status': 'success',
        'data': data,
        '_source': f'gateway_executor:{worker_hostname}'
    }

    # Debug logging to trace callback payload
    logger.info(f"GATEWAY.CALLBACK: Payload data type: {type(data)}")
    logger.info(f"GATEWAY.CALLBACK: Payload data: {json.dumps(data, default=str) if isinstance(data, dict) else data}")
    logger.info(f"GATEWAY.CALLBACK: Full payload: {json.dumps(payload, default=str)}")

    # Publish to NATS
    success = await _publish_callback(callback_subject, payload)

    if success:
        logger.info(f"GATEWAY.CALLBACK: Published to {callback_subject} for request_id={request_id}")
        return {
            'id': task_id,
            'status': 'success',
            'data': {
                'published': True,
                'subject': callback_subject,
                'request_id': request_id
            }
        }
    else:
        return {
            'id': task_id,
            'status': 'error',
            'error': 'Failed to publish callback'
        }


async def _execute_http_callback(
    task_id: str,
    task_name: str,
    start_time: datetime.datetime,
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Dict[str, Any],
    callback_url: str
) -> Dict[str, Any]:
    """
    Execute HTTP callback as fallback when NATS is not configured.
    """
    import httpx

    workload = context.get('workload', {})
    job = context.get('job', {})

    request_id = workload.get('request_id', '')
    execution_id = job.get('execution_id', '')

    raw_data = task_config.get('data', {})
    data = render_template(jinja_env, raw_data, context)
    step_name = task_config.get('step', context.get('current_step', 'unknown'))

    payload = {
        'request_id': request_id,
        'execution_id': execution_id,
        'step': step_name,
        'status': 'success',
        'data': data
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                callback_url,
                json=payload,
                headers={'Content-Type': 'application/json'}
            )
            response.raise_for_status()

            logger.info(f"GATEWAY.HTTP_CALLBACK: Posted to {callback_url} for request_id={request_id}")
            return {
                'id': task_id,
                'status': 'success',
                'data': {
                    'delivered': True,
                    'url': callback_url,
                    'request_id': request_id
                }
            }
    except Exception as e:
        logger.error(f"GATEWAY.HTTP_CALLBACK: Failed - {e}")
        return {
            'id': task_id,
            'status': 'error',
            'error': f'HTTP callback failed: {e}'
        }


async def _execute_wait(
    task_id: str,
    task_name: str,
    start_time: datetime.datetime,
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Execute wait action - pause and wait for external input.

    This implements the "message catch event" pattern from BPMN.
    The workflow pauses until a matching message arrives via the gateway.

    Future enhancement - for now returns not implemented.
    """
    logger.warning("GATEWAY.WAIT: Wait action not yet implemented")
    return {
        'id': task_id,
        'status': 'error',
        'error': 'Wait action not yet implemented. See DSL enhancement Phase 3.'
    }


async def _execute_notify(
    task_id: str,
    task_name: str,
    start_time: datetime.datetime,
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Execute notify action - send notification event.

    This can be used to notify other systems or broadcast events.

    Future enhancement - for now returns not implemented.
    """
    logger.warning("GATEWAY.NOTIFY: Notify action not yet implemented")
    return {
        'id': task_id,
        'status': 'error',
        'error': 'Notify action not yet implemented. See DSL enhancement Phase 3.'
    }
