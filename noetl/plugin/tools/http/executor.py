"""
HTTP task executor for NoETL jobs.

Main execution logic for HTTP plugin actions.
"""

import uuid
import datetime
import httpx
import os
from urllib.parse import urlparse
from typing import Dict, Any, Optional, Callable
from jinja2 import Environment

from noetl.core.dsl.render import render_template
from noetl.core.logger import setup_logger
from noetl.worker.auth_resolver import resolve_auth
from noetl.worker.auth_compatibility import transform_credentials_to_auth, validate_auth_transition

from .auth import build_auth_headers
from .request import build_request_args, redact_sensitive_headers
from .response import process_response, create_mock_response

logger = setup_logger(__name__, include_location=True)


def execute_http_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Dict[str, Any],
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute an HTTP task.

    Args:
        task_config: The task configuration
        context: The context to use for rendering templates
        jinja_env: The Jinja2 environment for template rendering
        task_with: The rendered 'with' parameters dictionary
        log_event_callback: A callback function to log events

    Returns:
        A dictionary of the task result
    """
    logger.debug("=== HTTP.EXECUTE_HTTP_TASK: Function entry ===")
    logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Parameters - task_config={task_config}, task_with={task_with}")

    task_id = str(uuid.uuid4())
    task_name = task_config.get('task', 'http_task')
    start_time = datetime.datetime.now()

    # Apply backwards compatibility transformation for deprecated 'credentials' field
    validate_auth_transition(task_config, task_with)
    task_config, task_with = transform_credentials_to_auth(task_config, task_with)

    logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Generated task_id={task_id}")
    logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Task name={task_name}")
    logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Start time={start_time.isoformat()}")

    try:
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Rendering HTTP task configuration")
        method = task_config.get('method', 'GET').upper()
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: HTTP method={method}")

        # Support both 'endpoint' (preferred) and legacy 'url' key for backward compatibility
        raw_endpoint_template = task_config.get('endpoint') or task_config.get('url', '')
        logger.critical(f"HTTP.EXECUTE: raw_endpoint_template={raw_endpoint_template}")
        logger.critical(f"HTTP.EXECUTE: context keys={list(context.keys())}")
        logger.critical(f"HTTP.EXECUTE: patient_id in context={'patient_id' in context}, value={context.get('patient_id')}")
        endpoint = render_template(jinja_env, raw_endpoint_template, context)
        logger.critical(f"HTTP.EXECUTE: Rendered endpoint={endpoint}")
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Rendered endpoint={endpoint}")

        # Unified data model: render step.data and allow explicit data.query/data.body
        raw_data = task_config.get('data') if isinstance(task_config, dict) else None
        data_map = render_template(jinja_env, raw_data or {}, context)
        if not isinstance(data_map, dict):
            data_map = {}
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Rendered data={data_map}")

        # Direct params/payload (alternative to data.query/data.body)
        params = render_template(jinja_env, task_config.get('params', {}), context)
        payload = render_template(jinja_env, task_config.get('payload', {}), context)

        headers = render_template(jinja_env, task_config.get('headers', {}), context)
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Rendered headers={headers}")

        # Process unified auth system to add authentication headers
        auth_headers = _process_authentication(task_config, task_with, jinja_env, context)
        if auth_headers:
            logger.debug(f"HTTP: Applying {len(auth_headers)} auth headers")
            headers.update(auth_headers)

        timeout = task_config.get('timeout', 30)
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Timeout={timeout}")

        event_id = None
        if log_event_callback:
            logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Writing task_start event log")
            event_id = log_event_callback(
                'task_start', task_id, task_name, 'http',
                'in_progress', 0, context, None,
                {'method': method, 'endpoint': endpoint, 'with_params': task_with}, None
            )

        try:
            # Check for local domain mocking
            if _should_mock_request(endpoint):
                logger.info(f"HTTP.EXECUTE_HTTP_TASK: Mocking request to local domain: {endpoint}")
                mock_data = create_mock_response(endpoint, method, params, payload, data_map)
                return _complete_task(
                    task_id, task_name, start_time, 'success', mock_data,
                    method, endpoint, task_with, context, event_id, log_event_callback,
                    mocked=True
                )

            # Execute the actual HTTP request
            logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Creating HTTP client with timeout={timeout}")
            with httpx.Client(timeout=timeout) as client:
                request_args = build_request_args(
                    endpoint, method, headers, data_map, params, payload
                )
                
                # Log request with redacted sensitive headers
                redacted_headers = redact_sensitive_headers(headers)
                logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Request headers (redacted)={redacted_headers}")
                logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Final request_args={request_args}")
                logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Making HTTP request")
                
                response = client.request(method, **request_args)
                logger.debug(f"HTTP.EXECUTE_HTTP_TASK: HTTP response received - status_code={response.status_code}")

                response_data = process_response(response)
                is_success = response.is_success
                logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Request success status={is_success}")

                result = {
                    'id': task_id,
                    'status': 'success' if is_success else 'error',
                    'data': response_data
                }

                if not is_success:
                    result['error'] = f"HTTP {response.status_code}: {response.reason_phrase}"
                    logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Request failed with error={result['error']}")

                return _complete_task(
                    task_id, task_name, start_time, result['status'], result.get('data'),
                    method, endpoint, task_with, context, event_id, log_event_callback
                )

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP error: {e.response.status_code} - {e.response.text}"
            logger.error(f"HTTP.EXECUTE_HTTP_TASK: HTTPStatusError - {error_msg}")
            raise Exception(error_msg)
        except httpx.RequestError as e:
            error_msg = f"Request error: {str(e)}"
            logger.error(f"HTTP.EXECUTE_HTTP_TASK: RequestError - {error_msg}")
            # Optionally mock on error in dev
            if _should_mock_on_error():
                mock_data = create_mock_response(endpoint, method, params, payload, data_map, "error_fallback")
                mock_data['data']['error'] = error_msg
                return _complete_task(
                    task_id, task_name, start_time, 'success', mock_data,
                    method, endpoint, task_with, context, event_id, log_event_callback,
                    mocked=True
                )
            raise Exception(error_msg)
        except httpx.TimeoutException as e:
            error_msg = f"Request timeout: {str(e)}"
            logger.error(f"HTTP.EXECUTE_HTTP_TASK: TimeoutException - {error_msg}")
            raise Exception(error_msg)

    except Exception as e:
        error_msg = str(e)
        logger.error(f"HTTP.EXECUTE_HTTP_TASK: Exception - {error_msg}", exc_info=True)
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Task duration={duration} seconds (error path)")

        if log_event_callback:
            logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Writing task_error event log")
            log_event_callback(
                'task_error', task_id, task_name, 'http',
                'error', duration, context, None,
                {'error': error_msg, 'with_params': task_with}, event_id
            )

        result = {
            'id': task_id,
            'status': 'error',
            'error': error_msg
        }
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Returning error result={result}")
        logger.debug("=== HTTP.EXECUTE_HTTP_TASK: Function exit (error) ===")
        return result


def _process_authentication(
    task_config: Dict[str, Any],
    task_with: Dict[str, Any],
    jinja_env: Environment,
    context: Dict[str, Any]
) -> Dict[str, str]:
    """
    Process authentication configuration and build auth headers.
    
    Args:
        task_config: Task configuration
        task_with: Task with parameters
        jinja_env: Jinja2 environment
        context: Execution context
        
    Returns:
        Dictionary of authentication headers
    """
    try:
        auth_config = task_config.get('auth') or task_with.get('auth')
        if auth_config:
            logger.debug("HTTP: Using unified auth system")
            mode, resolved_items = resolve_auth(auth_config, jinja_env, context)
            
            if resolved_items:
                return build_auth_headers(resolved_items, mode)
            else:
                logger.debug("HTTP: Auth config provided but resolution failed")
        else:
            logger.debug("HTTP: No auth configuration found")
    except Exception as e:
        logger.debug(f"HTTP: Unified auth processing failed: {e}", exc_info=True)
    
    return {}


def _should_mock_request(endpoint: str) -> bool:
    """
    Determine if request should be mocked based on endpoint and environment.
    
    Args:
        endpoint: Target endpoint URL
        
    Returns:
        True if request should be mocked
    """
    if not isinstance(endpoint, str):
        raise ValueError(f"endpoint must be a string, got {type(endpoint).__name__}")
    
    parsed = urlparse(endpoint)
    host = (parsed.hostname or '').lower() if parsed else ''
    
    mock_local = os.getenv('NOETL_HTTP_MOCK_LOCAL')
    if mock_local is None:
        mock_local = 'true' if os.getenv('NOETL_DEBUG', '').lower() == 'true' else 'false'
    mock_local = mock_local.lower() == 'true'
    
    return host.endswith('.local') and mock_local


def _should_mock_on_error() -> bool:
    """
    Determine if errors should be mocked in development.
    
    Returns:
        True if errors should be mocked
    """
    return os.getenv('NOETL_HTTP_MOCK_ON_ERROR', 'false').lower() == 'true'


def _complete_task(
    task_id: str,
    task_name: str,
    start_time: datetime.datetime,
    status: str,
    data: Any,
    method: str,
    endpoint: str,
    task_with: Dict[str, Any],
    context: Dict[str, Any],
    event_id: Optional[str],
    log_event_callback: Optional[Callable],
    mocked: bool = False
) -> Dict[str, Any]:
    """
    Complete task execution and log results.
    
    Args:
        task_id: Task identifier
        task_name: Task name
        start_time: Task start time
        status: Task status ('success' or 'error')
        data: Task result data
        method: HTTP method
        endpoint: Target endpoint
        task_with: Task with parameters
        context: Execution context
        event_id: Event identifier
        log_event_callback: Event logging callback
        mocked: Whether response was mocked
        
    Returns:
        Task result dictionary
    """
    end_time = datetime.datetime.now()
    duration = (end_time - start_time).total_seconds()
    logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Task duration={duration} seconds")

    if log_event_callback:
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Writing task_complete event log")
        meta = {'method': method, 'endpoint': endpoint, 'with_params': task_with}
        if mocked:
            meta['mocked'] = True
        log_event_callback(
            'task_complete', task_id, task_name, 'http',
            status, duration, context, data, meta, event_id
        )

    result = {'id': task_id, 'status': status, 'data': data}
    logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Returning result={result}")
    logger.debug("=== HTTP.EXECUTE_HTTP_TASK: Function exit (success) ===")
    return result
