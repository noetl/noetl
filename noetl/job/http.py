"""
HTTP action executor for NoETL jobs.
"""

import uuid
import datetime
import httpx
import os
from urllib.parse import urlparse
from typing import Dict, Any, Optional, Callable
from jinja2 import Environment

from noetl.render import render_template
from noetl.logger import setup_logger

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

    logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Generated task_id={task_id}")
    logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Task name={task_name}")
    logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Start time={start_time.isoformat()}")

    try:
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Rendering HTTP task configuration")
        method = task_config.get('method', 'GET').upper()
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: HTTP method={method}")

        endpoint = render_template(jinja_env, task_config.get('endpoint', ''), context)
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Rendered endpoint={endpoint}")

        params = render_template(jinja_env, task_config.get('params', {}), context)
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Rendered params={params}")

        payload = render_template(jinja_env, task_config.get('payload', {}), context)
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Rendered payload={payload}")

        headers = render_template(jinja_env, task_config.get('headers', {}), context)
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Rendered headers={headers}")

        timeout = task_config.get('timeout', 30)
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Timeout={timeout}")

        logger.info(f"HTTP.EXECUTE_HTTP_TASK: Executing HTTP {method} request to {endpoint}")

        event_id = None
        if log_event_callback:
            logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Writing task_start event log")
            event_id = log_event_callback(
                'task_start', task_id, task_name, 'http',
                'in_progress', 0, context, None,
                {'method': method, 'endpoint': endpoint, 'with_params': task_with}, None
            )

        headers = render_template(jinja_env, task_config.get('headers', {}), context)
        timeout = task_config.get('timeout', 30)

        try:
            # Pre-flight mocking for local/dev domains
            parsed = None
            try:
                parsed = urlparse(str(endpoint))
            except Exception:
                parsed = None
            host = (parsed.hostname or '').lower() if parsed else ''
            mock_local = os.getenv('NOETL_HTTP_MOCK_LOCAL')
            if mock_local is None:
                mock_local = 'true' if os.getenv('NOETL_DEBUG', '').lower() == 'true' else 'false'
            mock_local = mock_local.lower() == 'true'

            # If endpoint hostname is *.local and mocking is enabled, return a mocked success response
            if host.endswith('.local') and mock_local:
                logger.info(f"HTTP.EXECUTE_HTTP_TASK: Mocking request to local domain: {endpoint}")
                mock_data = {
                    'status_code': 200,
                    'headers': {},
                    'url': str(endpoint),
                    'elapsed': 0,
                    'data': {'mocked': True, 'endpoint': str(endpoint), 'method': method, 'params': params, 'payload': payload}
                }
                end_time = datetime.datetime.now()
                duration = (end_time - start_time).total_seconds()
                if log_event_callback:
                    log_event_callback(
                        'task_complete', task_id, task_name, 'http',
                        'success', duration, context, mock_data,
                        {'method': method, 'endpoint': endpoint, 'with_params': task_with, 'mocked': True}, event_id
                    )
                return {'id': task_id, 'status': 'success', 'data': mock_data}

            logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Creating HTTP client with timeout={timeout}")
            with httpx.Client(timeout=timeout) as client:
                request_args = {
                    'url': endpoint,
                    'headers': headers,
                    'params': params
                }
                logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Initial request_args={request_args}")

                if method in ['POST', 'PUT', 'PATCH'] and payload:
                    logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Processing payload for {method} request")
                    content_type = headers.get('Content-Type', '').lower()
                    logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Content-Type={content_type}")

                    if 'application/json' in content_type:
                        request_args['json'] = payload
                        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Using JSON payload")
                    elif 'application/x-www-form-urlencoded' in content_type:
                        request_args['data'] = payload
                        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Using form data payload")
                    elif 'multipart/form-data' in content_type:
                        request_args['files'] = payload
                        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Using multipart form data payload")
                    else:
                        if isinstance(payload, (dict, list)):
                            request_args['json'] = payload
                            logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Using default JSON payload for dict/list")
                        else:
                            request_args['data'] = payload
                            logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Using data payload for non-dict/list")

                logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Final request_args={request_args}")
                logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Making HTTP request")
                response = client.request(method, **request_args)
                logger.debug(f"HTTP.EXECUTE_HTTP_TASK: HTTP response received - status_code={response.status_code}")

                response_data = {
                    'status_code': response.status_code,
                    'headers': dict(response.headers),
                    'url': str(response.url),
                    'elapsed': response.elapsed.total_seconds() if hasattr(response, 'elapsed') else None
                }
                logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Response metadata={response_data}")

                try:
                    response_content_type = response.headers.get('Content-Type', '').lower()
                    logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Response Content-Type={response_content_type}")

                    if 'application/json' in response_content_type:
                        response_data['data'] = response.json()
                        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Parsed JSON response data")
                    else:
                        response_data['data'] = response.text
                        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Using text response data")
                except Exception as e:
                    logger.warning(f"HTTP.EXECUTE_HTTP_TASK: Failed to parse response content: {str(e)}")
                    response_data['data'] = response.text

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

                end_time = datetime.datetime.now()
                duration = (end_time - start_time).total_seconds()
                logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Task duration={duration} seconds")

                if log_event_callback:
                    logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Writing task_complete event log")
                    log_event_callback(
                        'task_complete', task_id, task_name, 'http',
                        result['status'], duration, context, result.get('data'),
                        {'method': method, 'endpoint': endpoint, 'with_params': task_with}, event_id
                    )

                logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Returning result={result}")
                logger.debug("=== HTTP.EXECUTE_HTTP_TASK: Function exit (success) ===")
                return result

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP error: {e.response.status_code} - {e.response.text}"
            logger.error(f"HTTP.EXECUTE_HTTP_TASK: HTTPStatusError - {error_msg}")
            raise Exception(error_msg)
        except httpx.RequestError as e:
            error_msg = f"Request error: {str(e)}"
            logger.error(f"HTTP.EXECUTE_HTTP_TASK: RequestError - {error_msg}")
            # Optionally mock on error in dev
            mock_on_error = os.getenv('NOETL_HTTP_MOCK_ON_ERROR', 'false').lower() == 'true'
            if mock_on_error:
                mock_data = {
                    'status_code': 200,
                    'headers': {},
                    'url': str(endpoint),
                    'elapsed': 0,
                    'data': {'mocked': True, 'error': error_msg}
                }
                end_time = datetime.datetime.now()
                duration = (end_time - start_time).total_seconds()
                if log_event_callback:
                    log_event_callback(
                        'task_complete', task_id, task_name, 'http',
                        'success', duration, context, mock_data,
                        {'method': method, 'endpoint': endpoint, 'with_params': task_with, 'mocked': True}, event_id
                    )
                return {'id': task_id, 'status': 'success', 'data': mock_data}
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


__all__ = ['execute_http_task']
