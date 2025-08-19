import os
import uuid
import datetime
import json
from typing import Dict, Any

import httpx
from jinja2 import Environment

from noetl.common import DateTimeEncoder, make_serializable
from noetl.logger import setup_logger
from noetl.render import render_template

logger = setup_logger(__name__, include_location=True)


def execute_http_task(task_config: Dict, context: Dict, jinja_env: Environment, task_with: Dict, log_event_callback=None) -> Dict:
    """
    Execute an HTTP task.
    """
    logger.debug("=== HTTP.EXECUTE_TASK: Function entry ===")
    logger.debug(f"HTTP.EXECUTE_TASK: Parameters - task_config={task_config}, task_with={task_with}")

    task_id = str(uuid.uuid4())
    task_name = task_config.get('task', 'http_task')
    start_time = datetime.datetime.now()

    try:
        method = task_config.get('method', 'GET').upper()

        endpoint = render_template(jinja_env, task_config.get('endpoint', ''), context)

        try:
            if isinstance(endpoint, str) and ('{{' in endpoint or '}}' in endpoint):
                logger.info("HTTP.EXECUTE_TASK: Endpoint appears unresolved after rendering; applying fallback resolution")
                suffix = ''
                try:
                    if '}}' in endpoint:
                        suffix = endpoint.split('}}', 1)[1].strip()
                except Exception:
                    suffix = ''
                env_map = context.get('env', {}) if isinstance(context, dict) else {}
                workload_map = context.get('workload', {}) if isinstance(context, dict) else {}
                base_url = (
                    (env_map.get('NOETL_BASE_URL') if isinstance(env_map, dict) else None)
                    or os.environ.get('NOETL_BASE_URL')
                    or (workload_map.get('noetl_base_url') if isinstance(workload_map, dict) else None)
                    or os.environ.get('NOETL_INTERNAL_URL')
                )
                if not base_url:
                    port = os.environ.get('NOETL_PORT', '8084')
                    base_url = f"http://localhost:{port}"
                base_url = str(base_url).rstrip('/')
                if suffix and not suffix.startswith('/'):
                    suffix = '/' + suffix
                endpoint = base_url + suffix
                logger.info(f"HTTP.EXECUTE_TASK: Fallback-resolved endpoint to {endpoint}")
        except Exception:
            pass

        try:
            def _resolve_base_url() -> str:
                env_map = context.get('env', {}) if isinstance(context, dict) else {}
                workload_map = context.get('workload', {}) if isinstance(context, dict) else {}
                base = (
                    (env_map.get('NOETL_BASE_URL') if isinstance(env_map, dict) else None)
                    or os.environ.get('NOETL_BASE_URL')
                    or (workload_map.get('noetl_base_url') if isinstance(workload_map, dict) else None)
                    or os.environ.get('NOETL_INTERNAL_URL')
                )
                if not base:
                    svc_host = os.environ.get('NOETL_SERVICE_HOST', '').strip()
                    svc_port = os.environ.get('NOETL_SERVICE_PORT', '').strip() or os.environ.get('NOETL_PORT', '').strip()
                    if svc_host and svc_port:
                        base = f"http://{svc_host}:{svc_port}"
                if not base:
                    port = os.environ.get('NOETL_PORT', '8084')
                    base = f"http://localhost:{port}"
                return str(base).rstrip('/')

            from urllib.parse import urlparse
            base_url_norm = _resolve_base_url()
            if not isinstance(endpoint, str) or not endpoint.strip():
                endpoint = base_url_norm
            else:
                parsed_ep = urlparse(endpoint)
                if not parsed_ep.scheme:
                    if endpoint.startswith('/'):
                        endpoint = base_url_norm + endpoint
                    else:
                        endpoint = base_url_norm + '/' + endpoint
        except Exception:
            pass

        try:
            from urllib.parse import urlparse as _urlparse
            _p = _urlparse(endpoint if isinstance(endpoint, str) else '')
            if not _p.scheme:
                raise ValueError(f"Request URL is missing an 'http://' or 'https://' protocol. Computed endpoint: '{endpoint}'")
        except Exception as _final_guard_err:
            error_msg = f"Request error: {str(_final_guard_err)}"
            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()
            if log_event_callback:
                log_event_callback(
                    'task_error', task_id, task_name, 'http',
                    'error', duration, context, None,
                    {'error': error_msg, 'with_params': task_with}, None
                )
            return {
                'id': task_id,
                'status': 'error',
                'error': error_msg
            }

        headers = task_config.get('headers', {})
        if headers:
            headers = render_template(jinja_env, headers, context)
        params = task_config.get('params', {})
        if params:
            params = render_template(jinja_env, params, context)
        body = task_config.get('body')
        if body is not None:
            body = render_template(jinja_env, body, context)

        def _build_timeout(cfg) -> httpx.Timeout:
            t = cfg.get('timeout', 30)
            if isinstance(t, (int, float)):
                return httpx.Timeout(timeout=t)
            if isinstance(t, dict):
                return httpx.Timeout(
                    connect=float(t.get('connect', 5)),
                    read=float(t.get('read', 30)),
                    write=float(t.get('write', 30)),
                    pool=float(t.get('pool', 30)),
                )
            return httpx.Timeout(timeout=30.0)

        timeout = _build_timeout(task_config)

        event_id = None
        if log_event_callback:
            event_id = log_event_callback(
                'task_start', task_id, task_name, 'http',
                'in_progress', 0, context, None,
                {'with_params': task_with}, None
            )

        with httpx.Client(timeout=timeout) as client:
            resp = client.request(method, endpoint, headers=headers, params=params, json=body)
            try:
                resp.raise_for_status()
            except Exception as e:
                error_msg = f"HTTP request failed: {e}"
                end_time = datetime.datetime.now()
                duration = (end_time - start_time).total_seconds()
                if log_event_callback:
                    log_event_callback(
                        'task_error', task_id, task_name, 'http',
                        'error', duration, context, None,
                        {'error': error_msg, 'with_params': task_with, 'status_code': resp.status_code, 'text': resp.text}, event_id
                    )
                return {
                    'id': task_id,
                    'status': 'error',
                    'error': error_msg
                }

            try:
                data = resp.json()
            except Exception:
                data = {'text': resp.text}

        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()

        if log_event_callback:
            log_event_callback(
                'task_complete', task_id, task_name, 'http',
                'success', duration, context, data,
                {'with_params': task_with, 'status_code': resp.status_code}, event_id
            )

        return {
            'id': task_id,
            'status': 'success',
            'data': data
        }

    except Exception as e:
        error_msg = str(e)
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()

        if log_event_callback:
            log_event_callback(
                'task_error', task_id, task_name, 'http',
                'error', duration, context, None,
                {'error': error_msg, 'with_params': task_with}, None
            )

        return {
            'id': task_id,
            'status': 'error',
            'error': error_msg
        }


__all__ = ["execute_http_task"]
