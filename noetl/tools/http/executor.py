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
from noetl.core.auth.resolver import resolve_auth_map
from noetl.worker.auth_compatibility import transform_credentials_to_auth, validate_auth_transition
from noetl.worker.keychain_resolver import populate_keychain_context

from .auth import build_auth_headers
from .request import build_request_args, redact_sensitive_headers
from .response import process_response, create_mock_response

logger = setup_logger(__name__, include_location=True)


async def execute_http_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Dict[str, Any],
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute an HTTP task with async authentication resolution and credential caching.

    Supports pagination via 'pagination' configuration block at task level.

    Args:
        task_config: The task configuration
        context: The context to use for rendering templates
        jinja_env: The Jinja2 environment for template rendering
        task_with: The rendered 'with' parameters dictionary
        log_event_callback: Optional callback for logging events (used by sink operations)

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
    
    # Standard HTTP execution (pagination/polling now handled by unified retry system)

    try:
        # STEP 1: Populate keychain context FIRST before any template rendering
        # This resolves {{ keychain.* }} references from the keychain API
        catalog_id = context.get('catalog_id')
        if catalog_id:
            execution_id = context.get('execution_id')
            server_url = context.get('server_url', 'http://noetl.noetl.svc.cluster.local:8082')
            context = await populate_keychain_context(
                task_config=task_config,
                context=context,
                catalog_id=catalog_id,
                execution_id=execution_id,
                api_base_url=server_url
            )
            logger.debug(f"HTTP: Keychain context populated: {list(context.get('keychain', {}).keys())}")
        else:
            logger.warning("HTTP: No catalog_id in context, skipping keychain resolution")
            
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Rendering HTTP task configuration")
        method = task_config.get('method', 'GET').upper()
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: HTTP method={method}")

        # Support both 'endpoint' (preferred) and legacy 'url' key for backward compatibility
        # Allow overrides via task_with (used by pagination retry)
        raw_endpoint_template = (
            task_with.get('endpoint')
            or task_with.get('url')
            or task_config.get('endpoint')
            or task_config.get('url', '')
        )
        logger.critical(f"HTTP.EXECUTE: raw_endpoint_template={raw_endpoint_template}")
        logger.critical(f"HTTP.EXECUTE: context keys={list(context.keys())}")
        logger.critical(f"HTTP.EXECUTE: patient_id in context={'patient_id' in context}, value={context.get('patient_id')}")
        endpoint = render_template(jinja_env, raw_endpoint_template, context)
        logger.critical(f"HTTP.EXECUTE: Rendered endpoint={endpoint}")
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Rendered endpoint={endpoint}")

        # Process authentication FIRST and add to context for template rendering
        auth_headers, resolved_auth_map = await _process_authentication_with_context(task_config, task_with, jinja_env, context)
        if resolved_auth_map:
            logger.debug(f"HTTP: Adding {len(resolved_auth_map)} resolved auth items to context")
            context['auth'] = resolved_auth_map
        
        # Now render data/payload with auth in context
        # Unified data model: render step.data and allow explicit data.query/data.body
        raw_data = task_config.get('data') if isinstance(task_config, dict) else None
        data_map = render_template(jinja_env, raw_data or {}, context)
        if not isinstance(data_map, dict):
            data_map = {}
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Rendered data={data_map}")

        # Direct params/payload (alternative to data.query/data.body)
        params = render_template(jinja_env, task_config.get('params', {}), context)
        payload = render_template(jinja_env, task_config.get('payload', {}), context)

        # Apply runtime overrides from task_with (e.g., pagination retry params)
        if isinstance(task_with, dict):
            if isinstance(task_with.get('params'), dict):
                params = {**params, **task_with['params']}
            if isinstance(task_with.get('payload'), dict):
                payload = {**payload, **task_with['payload']}
            if isinstance(task_with.get('headers'), dict):
                headers = {**headers, **task_with['headers']}
            if isinstance(task_with.get('data'), dict):
                # Merge into data_map for completeness
                data_map.update(task_with['data'])

        headers = render_template(jinja_env, task_config.get('headers', {}), context)
        logger.info(f"HTTP.EXECUTE_HTTP_TASK: Rendered headers (raw keys)={list(headers.keys())}")

        # Apply auth headers (already processed above)
        if auth_headers:
            logger.info(f"HTTP: Applying {len(auth_headers)} auth headers")
            headers.update(auth_headers)

        # Log a safe preview of Authorization to debug token resolution without leaking secrets
        auth_header = headers.get('Authorization')
        if auth_header:
            preview = auth_header
            if isinstance(auth_header, str) and len(auth_header) > 24:
                preview = f"{auth_header[:12]}...{auth_header[-6:]}"
            logger.info(
                f"HTTP.EXECUTE_HTTP_TASK: Authorization header present (len={len(auth_header) if isinstance(auth_header, str) else 'n/a'}, preview={preview})"
            )
        redacted_headers = redact_sensitive_headers(headers)
        logger.info(f"HTTP.EXECUTE_HTTP_TASK: Headers (redacted)={redacted_headers}")

        timeout = task_config.get('timeout', 30)
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Timeout={timeout}")

        try:
            # Check for local domain mocking
            if _should_mock_request(endpoint):
                logger.info(f"HTTP.EXECUTE_HTTP_TASK: Mocking request to local domain: {endpoint}")
                mock_data = create_mock_response(endpoint, method, params, payload, data_map)
                return _complete_task(
                    task_id, task_name, start_time, 'success', mock_data,
                    method, endpoint, task_with, mocked=True
                )

            # Execute the actual HTTP request
            logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Creating HTTP client with timeout={timeout}")
            with httpx.Client(timeout=timeout) as client:
                request_args = build_request_args(
                    endpoint, method, headers, data_map, params, payload
                )
                
                # Log request with redacted sensitive headers
                redacted_headers = redact_sensitive_headers(headers)
                logger.info(f"HTTP.EXECUTE_HTTP_TASK: Request headers (redacted)={redacted_headers}")
                logger.info(f"HTTP.EXECUTE_HTTP_TASK: Final request_args={request_args}")
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
                    method, endpoint, task_with
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
                    method, endpoint, task_with, mocked=True
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

        result = {
            'id': task_id,
            'status': 'error',
            'error': error_msg
        }
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Returning error result={result}")
        logger.debug("=== HTTP.EXECUTE_HTTP_TASK: Function exit (error) ===")
        return result


async def _process_authentication_with_context(
    task_config: Dict[str, Any],
    task_with: Dict[str, Any],
    jinja_env: Environment,
    context: Dict[str, Any]
) -> tuple[Dict[str, str], Dict[str, Any]]:
    """
    Process authentication configuration, build auth headers, and return resolved auth map.
    
    Args:
        task_config: Task configuration
        task_with: Task with parameters
        jinja_env: Jinja2 environment
        context: Execution context
        
    Returns:
        Tuple of (auth_headers, resolved_auth_map) where resolved_auth_map can be used in templates
    """
    try:
        auth_config = task_config.get('auth') or task_with.get('auth')
        if auth_config:
            logger.debug("HTTP: Using unified auth system")
            resolved_auth = await resolve_auth_map(step_config=task_config, task_with=task_with, jinja_env=jinja_env, context=context)
            
            if resolved_auth:
                # Build headers from resolved auth
                # For HTTP, we need to convert the resolved auth dict to headers
                headers = {}
                for alias, cred_data in resolved_auth.items():
                    auth_type = cred_data.get('type')
                    if auth_type == 'bearer':
                        token = cred_data.get('token') or cred_data.get('value')
                        if token:
                            headers['Authorization'] = f'Bearer {token}'
                    elif auth_type == 'api_key':
                        header_name = cred_data.get('header_name', 'X-API-Key')
                        api_key = cred_data.get('api_key') or cred_data.get('value')
                        if api_key:
                            headers[header_name] = api_key
                    elif auth_type == 'basic':
                        import base64
                        username = cred_data.get('username', '')
                        password = cred_data.get('password', '')
                        credentials = f'{username}:{password}'
                        encoded = base64.b64encode(credentials.encode()).decode()
                        headers['Authorization'] = f'Basic {encoded}'
                
                # Return headers and full resolved auth map for template context
                return headers, resolved_auth
            else:
                logger.debug("HTTP: Auth config provided but resolution failed")
        else:
            logger.debug("HTTP: No auth configuration found")
    except Exception as e:
        logger.debug(f"HTTP: Unified auth processing failed: {e}", exc_info=True)
    
    return {}, {}


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
    headers, _ = _process_authentication_with_context(task_config, task_with, jinja_env, context)
    return headers


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
    mocked: bool = False
) -> Dict[str, Any]:
    """
    Complete task execution and return result envelope.
    
    Args:
        task_id: Task identifier
        task_name: Task name
        start_time: Task start time
        status: Task status ('success' or 'error')
        data: Task result data
        method: HTTP method
        endpoint: Target endpoint
        task_with: Task with parameters
        mocked: Whether response was mocked

    Returns:
        Task result dictionary
    """
    end_time = datetime.datetime.now()
    duration = (end_time - start_time).total_seconds()
    logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Task duration={duration} seconds")

    result = {'id': task_id, 'status': status, 'data': data}
    logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Returning result={result}")
    logger.debug("=== HTTP.EXECUTE_HTTP_TASK: Function exit (success) ===")
    return result
