"""
HTTP task executor for NoETL jobs.

Main execution logic for HTTP plugin actions.
"""

import uuid
import datetime
import httpx
import os
import threading
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
from .response import process_response, create_mock_response, build_result_reference

logger = setup_logger(__name__, include_location=True)


def _safe_endpoint(endpoint: str) -> str:
    """Return a minimally identifying endpoint string without query/fragment."""
    parsed = urlparse(endpoint or "")
    if not parsed.scheme and not parsed.netloc:
        return str(endpoint or "")
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def _mapping_key_count(value: Any) -> int:
    return len(value.keys()) if isinstance(value, dict) else 0


def _request_shape_summary(request_args: Dict[str, Any]) -> Dict[str, Any]:
    summary = {
        "has_params": isinstance(request_args.get("params"), dict),
        "param_keys": _mapping_key_count(request_args.get("params")),
        "has_json": "json" in request_args,
        "has_data": "data" in request_args,
        "has_files": "files" in request_args,
        "json_keys": _mapping_key_count(request_args.get("json")),
        "data_keys": _mapping_key_count(request_args.get("data")),
        "file_keys": _mapping_key_count(request_args.get("files")),
    }
    if request_args.get("json") is not None and not isinstance(request_args.get("json"), dict):
        summary["json_type"] = type(request_args.get("json")).__name__
    if request_args.get("data") is not None and not isinstance(request_args.get("data"), dict):
        summary["data_type"] = type(request_args.get("data")).__name__
    if request_args.get("files") is not None and not isinstance(request_args.get("files"), dict):
        summary["files_type"] = type(request_args.get("files")).__name__
    return summary


def _read_int_env(name: str, default: int, min_value: int = 1) -> int:
    """Read integer env var with safe fallback."""
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return max(min_value, int(raw))
    except (TypeError, ValueError):
        return default


def _read_float_env(name: str, default: float, min_value: float = 0.1) -> float:
    """Read float env var with safe fallback."""
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return max(min_value, float(raw))
    except (TypeError, ValueError):
        return default


def _read_bool_env(name: str, default: bool) -> bool:
    """Read boolean env var with safe fallback."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


_HTTP_CLIENT_LOCK = threading.Lock()
_HTTP_CLIENTS: Dict[tuple[bool, bool], httpx.Client] = {}


def _get_shared_http_client(verify_ssl: bool, follow_redirects: bool) -> httpx.Client:
    """
    Return a shared keep-alive HTTP client for this worker process.

    This avoids creating/tearing down a client per HTTP task call, which is
    especially expensive for high-volume task_sequence loops.
    """
    key = (bool(verify_ssl), bool(follow_redirects))
    with _HTTP_CLIENT_LOCK:
        existing = _HTTP_CLIENTS.get(key)
        if existing is not None and not existing.is_closed:
            return existing

        limits = httpx.Limits(
            max_connections=_read_int_env("NOETL_HTTP_MAX_CONNECTIONS", 200),
            max_keepalive_connections=_read_int_env("NOETL_HTTP_MAX_KEEPALIVE_CONNECTIONS", 50),
            keepalive_expiry=_read_float_env("NOETL_HTTP_KEEPALIVE_EXPIRY_SECONDS", 30.0, min_value=1.0),
        )
        http2_enabled = _read_bool_env("NOETL_HTTP_ENABLE_HTTP2", True)
        try:
            client = httpx.Client(
                verify=verify_ssl,
                follow_redirects=follow_redirects,
                limits=limits,
                http2=http2_enabled,
            )
        except Exception as exc:
            # Graceful fallback when httpx HTTP/2 extras are not installed in runtime image.
            if http2_enabled and "h2" in str(exc).lower():
                logger.warning(
                    "HTTP/2 requested but h2 extras are unavailable; falling back to HTTP/1.1. "
                    "Set NOETL_HTTP_ENABLE_HTTP2=false to suppress this warning."
                )
                client = httpx.Client(
                    verify=verify_ssl,
                    follow_redirects=follow_redirects,
                    limits=limits,
                    http2=False,
                )
            else:
                raise
        _HTTP_CLIENTS[key] = client
        return client


async def execute_http_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Dict[str, Any],
    log_event_callback: Optional[Callable] = None,
    sink_config: Optional[Dict[str, Any]] = None
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
    logger.debug(
        "HTTP.EXECUTE_HTTP_TASK: Entry task_config_keys=%s task_with_keys=%s",
        _mapping_key_count(task_config),
        _mapping_key_count(task_with),
    )

    task_id = str(uuid.uuid4())
    task_name = task_config.get('task', 'http_task')
    start_time = datetime.datetime.now()

    # Apply backwards compatibility transformation for deprecated 'credentials' field
    validate_auth_transition(task_config, task_with)
    task_config, task_with = transform_credentials_to_auth(task_config, task_with)

    logger.debug(f"HTTP.EXECUTE_HTTP_TASK: task_id={task_id} | name={task_name} | start={start_time.isoformat()}")
    
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
            logger.debug(
                "HTTP: Keychain context populated (key_count=%s)",
                _mapping_key_count(context.get("keychain")),
            )
        else:
            logger.debug("HTTP: No catalog_id in context, skipping keychain resolution")
            
        method = task_config.get('method', 'GET').upper()
        logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Rendering HTTP task configuration | method={method}")

        # Support both 'endpoint' (preferred) and legacy 'url' key for backward compatibility
        # Allow overrides via task_with (used by pagination retry)
        raw_endpoint_template = (
            task_with.get('endpoint')
            or task_with.get('url')
            or task_config.get('endpoint')
            or task_config.get('url', '')
        )
        endpoint = render_template(jinja_env, raw_endpoint_template, context)
        logger.debug(
            "HTTP.EXECUTE: endpoint=%s context_keys=%s",
            _safe_endpoint(endpoint),
            _mapping_key_count(context),
        )

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
        logger.debug(
            "HTTP.EXECUTE_HTTP_TASK: Rendered data key_count=%s",
            _mapping_key_count(data_map),
        )

        # Direct params/payload (alternative to data.query/data.body)
        # Also support 'body' key as an alias for 'payload' (common pattern)
        params = render_template(jinja_env, task_config.get('params', {}), context)
        raw_payload = task_config.get('payload') or task_config.get('body')
        payload = render_template(jinja_env, raw_payload or {}, context)
        headers = render_template(jinja_env, task_config.get('headers', {}), context)

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

        # Apply auth headers (already processed above)
        if auth_headers:
            headers.update(auth_headers)

        # Log headers with sensitive values redacted (SECURITY: no tokens/passwords in logs)
        redacted_headers = redact_sensitive_headers(headers)
        logger.debug(
            "HTTP.EXECUTE_HTTP_TASK: headers_keys=%s auth_applied=%s redacted_headers=%s",
            list(headers.keys()),
            len(auth_headers) if auth_headers else 0,
            redacted_headers,
        )

        timeout = task_config.get('timeout', 30)
        verify_ssl = task_config.get('verify_ssl')
        if verify_ssl is None:
            verify_ssl = task_config.get('verify', True)
        follow_redirects = bool(task_config.get('follow_redirects', False))
        logger.debug(
            f"HTTP.EXECUTE_HTTP_TASK: Timeout={timeout} | verify_ssl={verify_ssl} | follow_redirects={follow_redirects}"
        )

        try:
            # Check for local domain mocking
            if _should_mock_request(endpoint):
                logger.debug("HTTP.EXECUTE_HTTP_TASK: Mocking request to local domain")
                mock_data = create_mock_response(endpoint, method, params, payload, data_map)
                # Apply sink-driven reference if sink is configured
                if sink_config:
                    mock_data = build_result_reference(mock_data, sink_config)
                return _complete_task(
                    task_id, task_name, start_time, 'success', mock_data,
                    method, endpoint, task_with, mocked=True, sink_config=sink_config
                )

            # Execute the actual HTTP request using shared keep-alive client
            client = _get_shared_http_client(bool(verify_ssl), follow_redirects)
            request_args = build_request_args(
                endpoint, method, headers, data_map, params, payload
            )

            redacted_headers = redact_sensitive_headers(headers)
            logger.debug(
                "HTTP.EXECUTE_HTTP_TASK: Request | method=%s endpoint=%s timeout=%s shared_client=true "
                "header_keys=%s redacted_headers=%s request_shape=%s",
                method,
                _safe_endpoint(endpoint),
                timeout,
                list(headers.keys()) if isinstance(headers, dict) else [],
                redacted_headers,
                _request_shape_summary(request_args),
            )

            response = client.request(method, timeout=timeout, **request_args)

            response_data = process_response(response)
            is_success = response.is_success
            logger.debug(f"HTTP.EXECUTE_HTTP_TASK: Response received | status={response.status_code} | success={is_success}")

            # Apply sink-driven reference if sink is configured
            if sink_config:
                logger.info(f"HTTP.EXECUTE_HTTP_TASK: Sink detected, building result reference")
                response_data = build_result_reference(response_data, sink_config)

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
                method, endpoint, task_with, sink_config=sink_config
            )

        except httpx.HTTPStatusError as e:
            error_msg = (
                f"HTTP error: status={e.response.status_code} "
                f"reason={e.response.reason_phrase} body_bytes={len(e.response.text or '')}"
            )
            logger.error(f"HTTP.EXECUTE_HTTP_TASK: HTTPStatusError - {error_msg}")
            raise Exception(error_msg)
        except httpx.RequestError as e:
            error_msg = f"Request error: {str(e)}"
            logger.error(f"HTTP.EXECUTE_HTTP_TASK: RequestError - {error_msg}")
            # Optionally mock on error in dev
            if _should_mock_on_error():
                mock_data = create_mock_response(endpoint, method, params, payload, data_map, "error_fallback")
                mock_data['data']['error'] = error_msg
                # Apply sink-driven reference if sink is configured
                if sink_config:
                    mock_data = build_result_reference(mock_data, sink_config)
                return _complete_task(
                    task_id, task_name, start_time, 'success', mock_data,
                    method, endpoint, task_with, mocked=True, sink_config=sink_config
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
        logger.debug(
            "HTTP.EXECUTE_HTTP_TASK: Exit (error) status=%s id=%s",
            result.get("status"),
            result.get("id"),
        )
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
    mocked: bool = False,
    sink_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Complete task execution and return result envelope.
    
    Args:
        task_id: Task identifier
        task_name: Task name
        start_time: Task start time
        status: Task status ('success' or 'error')
        data: Task result data (may contain data_reference if sink is present)
        method: HTTP method
        endpoint: Target endpoint
        task_with: Task with parameters
        mocked: Whether response was mocked
        sink_config: Optional sink configuration (triggers result reference pattern)

    Returns:
        Task result dictionary
    """
    end_time = datetime.datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    result = {'id': task_id, 'status': status, 'data': data}
    
    # Log based on whether sink reference was used
    if sink_config and isinstance(data, dict) and 'data_reference' in data:
        ref = data.get('data_reference', {})
        logger.info(
            f"HTTP.COMPLETE_TASK: Sink-driven result | duration={duration}s | "
            f"sink_type={ref.get('sink_type')} | table={ref.get('table')} | "
            f"row_count={ref.get('row_count')}"
        )
    else:
        logger.debug(f"HTTP.COMPLETE_TASK: Task duration={duration} seconds")
    
    logger.debug(
        "HTTP.COMPLETE_TASK: Exit (success) status=%s id=%s duration=%ss",
        result.get("status"),
        result.get("id"),
        round(duration, 3),
    )
    return result
