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

from noetl.core.dsl.render import render_template
from noetl.core.logger import setup_logger
from noetl.worker.auth_resolver import resolve_auth
from noetl.worker.auth_compatibility import transform_credentials_to_auth, validate_auth_transition

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
        endpoint = render_template(jinja_env, raw_endpoint_template, context)
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Rendered endpoint={endpoint}")

        # Unified data model: render step.data and allow explicit data.query/data.body
        raw_data = task_config.get('data') if isinstance(task_config, dict) else None
        data_map = render_template(jinja_env, raw_data or {}, context)
        if not isinstance(data_map, dict):
            data_map = {}
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Rendered data={data_map}")

        # Legacy back-compat: also accept params/payload when provided
        params_legacy = render_template(jinja_env, task_config.get('params', {}), context)
        payload_legacy = render_template(jinja_env, task_config.get('payload', {}), context)

        headers = render_template(jinja_env, task_config.get('headers', {}), context)
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Rendered headers={headers}")

        # Process unified auth system to add authentication headers
        try:
            auth_config = task_config.get('auth') or task_with.get('auth')
            if auth_config:
                logger.debug("HTTP: Using unified auth system")
                mode, resolved_items = resolve_auth(auth_config, jinja_env, context)
                
                if resolved_items:
                    # Build authentication headers based on auth type
                    auth_headers = {}
                    
                    # For HTTP plugin, we expect single auth mode or use the first resolved item
                    resolved_auth = None
                    if mode == 'single' or len(resolved_items) == 1:
                        resolved_auth = list(resolved_items.values())[0]
                    
                    if resolved_auth and resolved_auth.service == 'bearer':
                        # Bearer token authentication
                        token = resolved_auth.payload.get('token')
                        if token:
                            auth_headers['Authorization'] = f'Bearer {token}'
                            logger.debug("HTTP: Added Bearer authorization header")
                    
                    elif resolved_auth and resolved_auth.service == 'basic':
                        # Basic authentication
                        username = resolved_auth.payload.get('username') or resolved_auth.payload.get('user')
                        password = resolved_auth.payload.get('password')
                        if username and password:
                            import base64
                            credentials = base64.b64encode(f'{username}:{password}'.encode()).decode()
                            auth_headers['Authorization'] = f'Basic {credentials}'
                            logger.debug("HTTP: Added Basic authorization header")
                    
                    elif resolved_auth and resolved_auth.service == 'api_key':
                        # API key authentication
                        key = resolved_auth.payload.get('key')
                        value = resolved_auth.payload.get('value')
                        if key and value:
                            auth_headers[key] = value
                            logger.debug(f"HTTP: Added API key header: {key}")
                    
                    elif resolved_auth and resolved_auth.service == 'header':
                        # Direct header injection
                        header_config = resolved_auth.payload
                        if isinstance(header_config, dict):
                            auth_headers.update(header_config)
                            logger.debug(f"HTTP: Added custom headers: {list(header_config.keys())}")
                    
                    else:
                        logger.debug(f"HTTP: Unsupported auth type for HTTP injection: {resolved_auth.auth_type}")
                    
                    # Apply auth headers (they override user-specified headers)
                    if auth_headers:
                        logger.debug(f"HTTP: Applying {len(auth_headers)} auth headers")
                        headers.update(auth_headers)
                else:
                    logger.debug("HTTP: Auth config provided but resolution failed")
            else:
                logger.debug("HTTP: No auth configuration found")
        except Exception as e:
            logger.debug(f"HTTP: Unified auth processing failed: {e}", exc_info=True)

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
                    'data': {
                        'mocked': True,
                        'endpoint': str(endpoint),
                        'method': method,
                        'params': params_legacy,
                        'payload': payload_legacy,
                        'data': data_map
                    }
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
                }
                # Route data to query/body automatically with overrides
                params = None
                json_body = None
                try:
                    # Explicit overrides
                    if 'query' in data_map:
                        params = data_map.get('query') if isinstance(data_map.get('query'), dict) else None
                    if 'body' in data_map:
                        json_body = data_map.get('body')
                except Exception:
                    pass
                if method in ['GET', 'DELETE']:
                    if params is None:  # default: use whole data_map as query when no explicit query/body
                        if 'query' not in data_map and 'body' not in data_map:
                            params = {k: v for k, v in data_map.items()}
                    if params is None and isinstance(params_legacy, dict) and params_legacy:
                        params = params_legacy
                    if params:
                        request_args['params'] = params
                else:
                    # POST/PUT/PATCH methods
                    if json_body is None:
                        if 'query' not in data_map and 'body' not in data_map:
                            json_body = data_map
                        elif isinstance(payload_legacy, (dict, list)) and not json_body:
                            json_body = payload_legacy
                    if json_body is not None:
                        # Honor content-type if user set form/multipart; otherwise default to JSON
                        content_type = headers.get('Content-Type', '').lower()
                        if 'application/x-www-form-urlencoded' in content_type:
                            request_args['data'] = json_body
                        elif 'multipart/form-data' in content_type:
                            request_args['files'] = json_body
                        else:
                            request_args['json'] = json_body
                
                # Log request args with redacted sensitive headers
                redacted_headers = {}
                for k, v in (headers or {}).items():
                    if any(sensitive in k.lower() for sensitive in ['authorization', 'token', 'key', 'secret', 'password']):
                        redacted_headers[k] = '[REDACTED]'
                    else:
                        redacted_headers[k] = v
                logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Request headers (redacted)={redacted_headers}")
                logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Initial request_args (without sensitive headers)")

                # Remove legacy payload handling block (handled above via data routing)

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
