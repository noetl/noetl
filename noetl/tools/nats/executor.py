"""
NATS tool executor for JetStream, K/V Store, and Object Store operations.

Supported operations:
- kv_get: Get value from K/V store
- kv_put: Put value to K/V store
- kv_delete: Delete key from K/V store
- kv_keys: List keys in K/V bucket
- kv_purge: Purge key history from K/V store
- object_get: Get object from Object Store
- object_put: Put object to Object Store
- object_delete: Delete object from Object Store
- object_list: List objects in Object Store
- object_info: Get object metadata
- js_publish: Publish message to JetStream
- js_get_msg: Get message from JetStream by sequence
- js_stream_info: Get JetStream stream info

NOTE: No subscription/pull operations as they would block playbook execution.
"""

import asyncio
import base64
import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from jinja2 import Environment

from noetl.core.logger import setup_logger
from noetl.core.dsl.render import render_template
from .auth import resolve_nats_auth, get_nats_connection_params

logger = setup_logger(__name__, include_location=True)


async def _get_nats_client(conn_params: Dict):
    """Create and connect a NATS client."""
    import nats

    url = conn_params['url']
    user = conn_params.get('user')
    password = conn_params.get('password')
    token = conn_params.get('token')

    connect_kwargs = {}
    if user and password:
        connect_kwargs['user'] = user
        connect_kwargs['password'] = password
    elif token:
        connect_kwargs['token'] = token

    nc = await nats.connect(url, **connect_kwargs)
    return nc


async def _execute_kv_get(
    nc,
    bucket: str,
    key: str,
    **kwargs
) -> Dict[str, Any]:
    """Get value from K/V store."""
    js = nc.jetstream()

    try:
        kv = await js.key_value(bucket)
        entry = await kv.get(key)

        # Decode value
        value = entry.value.decode('utf-8') if entry.value else None

        # Try to parse as JSON
        try:
            value = json.loads(value) if value else None
        except (json.JSONDecodeError, TypeError):
            pass

        return {
            'status': 'success',
            'bucket': bucket,
            'key': key,
            'value': value,
            'revision': entry.revision,
            'created': entry.created.isoformat() if entry.created else None,
        }
    except Exception as e:
        error_msg = str(e)
        if 'key not found' in error_msg.lower() or 'no such key' in error_msg.lower():
            return {
                'status': 'not_found',
                'bucket': bucket,
                'key': key,
                'value': None,
            }
        raise


async def _execute_kv_put(
    nc,
    bucket: str,
    key: str,
    value: Any,
    ttl: Optional[int] = None,
    **kwargs
) -> Dict[str, Any]:
    """Put value to K/V store."""
    js = nc.jetstream()

    kv = await js.key_value(bucket)

    # Serialize value
    if isinstance(value, (dict, list)):
        data = json.dumps(value).encode('utf-8')
    elif isinstance(value, str):
        data = value.encode('utf-8')
    elif isinstance(value, bytes):
        data = value
    else:
        data = str(value).encode('utf-8')

    revision = await kv.put(key, data)

    return {
        'status': 'success',
        'bucket': bucket,
        'key': key,
        'revision': revision,
    }


async def _execute_kv_delete(
    nc,
    bucket: str,
    key: str,
    **kwargs
) -> Dict[str, Any]:
    """Delete key from K/V store."""
    js = nc.jetstream()

    kv = await js.key_value(bucket)
    await kv.delete(key)

    return {
        'status': 'success',
        'bucket': bucket,
        'key': key,
    }


async def _execute_kv_keys(
    nc,
    bucket: str,
    pattern: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """List keys in K/V bucket."""
    js = nc.jetstream()

    kv = await js.key_value(bucket)
    keys = await kv.keys()

    # Filter by pattern if provided
    if pattern:
        import fnmatch
        keys = [k for k in keys if fnmatch.fnmatch(k, pattern)]

    return {
        'status': 'success',
        'bucket': bucket,
        'keys': list(keys),
        'count': len(keys),
    }


async def _execute_kv_purge(
    nc,
    bucket: str,
    key: str,
    **kwargs
) -> Dict[str, Any]:
    """Purge key history from K/V store."""
    js = nc.jetstream()

    kv = await js.key_value(bucket)
    await kv.purge(key)

    return {
        'status': 'success',
        'bucket': bucket,
        'key': key,
    }


async def _execute_object_get(
    nc,
    bucket: str,
    name: str,
    encoding: str = 'utf-8',
    **kwargs
) -> Dict[str, Any]:
    """Get object from Object Store."""
    js = nc.jetstream()

    obs = await js.object_store(bucket)
    result = await obs.get(name)

    # Read data
    data = result.data if hasattr(result, 'data') else await result.read()

    # Decode based on encoding
    if encoding == 'base64':
        value = base64.b64encode(data).decode('ascii')
    elif encoding == 'binary':
        value = data
    else:
        value = data.decode(encoding)

    return {
        'status': 'success',
        'bucket': bucket,
        'name': name,
        'data': value,
        'size': len(data),
    }


async def _execute_object_put(
    nc,
    bucket: str,
    name: str,
    data: Any,
    encoding: str = 'utf-8',
    description: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """Put object to Object Store."""
    js = nc.jetstream()

    obs = await js.object_store(bucket)

    # Encode data
    if isinstance(data, bytes):
        binary_data = data
    elif encoding == 'base64':
        binary_data = base64.b64decode(data)
    else:
        binary_data = data.encode(encoding) if isinstance(data, str) else str(data).encode(encoding)

    info = await obs.put(name, binary_data)

    return {
        'status': 'success',
        'bucket': bucket,
        'name': name,
        'size': info.size if hasattr(info, 'size') else len(binary_data),
        'digest': info.digest if hasattr(info, 'digest') else None,
    }


async def _execute_object_delete(
    nc,
    bucket: str,
    name: str,
    **kwargs
) -> Dict[str, Any]:
    """Delete object from Object Store."""
    js = nc.jetstream()

    obs = await js.object_store(bucket)
    await obs.delete(name)

    return {
        'status': 'success',
        'bucket': bucket,
        'name': name,
    }


async def _execute_object_list(
    nc,
    bucket: str,
    **kwargs
) -> Dict[str, Any]:
    """List objects in Object Store."""
    js = nc.jetstream()

    obs = await js.object_store(bucket)
    objects = []

    async for info in obs.list():
        objects.append({
            'name': info.name,
            'size': info.size,
            'mtime': info.mtime.isoformat() if info.mtime else None,
            'digest': info.digest,
        })

    return {
        'status': 'success',
        'bucket': bucket,
        'objects': objects,
        'count': len(objects),
    }


async def _execute_object_info(
    nc,
    bucket: str,
    name: str,
    **kwargs
) -> Dict[str, Any]:
    """Get object metadata from Object Store."""
    js = nc.jetstream()

    obs = await js.object_store(bucket)
    info = await obs.info(name)

    return {
        'status': 'success',
        'bucket': bucket,
        'name': name,
        'size': info.size,
        'mtime': info.mtime.isoformat() if info.mtime else None,
        'digest': info.digest,
        'chunks': info.chunks if hasattr(info, 'chunks') else None,
    }


async def _execute_js_publish(
    nc,
    stream: str,
    subject: str,
    data: Any,
    headers: Optional[Dict[str, str]] = None,
    **kwargs
) -> Dict[str, Any]:
    """Publish message to JetStream."""
    js = nc.jetstream()

    # Serialize data
    if isinstance(data, (dict, list)):
        payload = json.dumps(data).encode('utf-8')
    elif isinstance(data, str):
        payload = data.encode('utf-8')
    elif isinstance(data, bytes):
        payload = data
    else:
        payload = str(data).encode('utf-8')

    # Publish with ack
    ack = await js.publish(subject, payload, headers=headers)

    return {
        'status': 'success',
        'stream': ack.stream,
        'seq': ack.seq,
        'duplicate': ack.duplicate if hasattr(ack, 'duplicate') else False,
    }


async def _execute_js_get_msg(
    nc,
    stream: str,
    seq: Optional[int] = None,
    last: bool = False,
    subject: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """Get message from JetStream by sequence number."""
    js = nc.jetstream()

    # Get stream
    stream_obj = await js.stream_info(stream)

    # Get raw message
    if last:
        msg = await js.get_msg(stream, last=True)
    elif seq:
        msg = await js.get_msg(stream, seq=seq)
    elif subject:
        msg = await js.get_msg(stream, subject=subject, last=True)
    else:
        raise ValueError("Must specify 'seq', 'last=true', or 'subject'")

    # Decode data
    data = msg.data.decode('utf-8') if msg.data else None
    try:
        data = json.loads(data) if data else None
    except (json.JSONDecodeError, TypeError):
        pass

    return {
        'status': 'success',
        'stream': stream,
        'subject': msg.subject,
        'seq': msg.seq,
        'data': data,
        'time': msg.time.isoformat() if hasattr(msg, 'time') and msg.time else None,
        'headers': dict(msg.headers) if msg.headers else None,
    }


async def _execute_js_stream_info(
    nc,
    stream: str,
    **kwargs
) -> Dict[str, Any]:
    """Get JetStream stream info."""
    js = nc.jetstream()

    info = await js.stream_info(stream)

    return {
        'status': 'success',
        'stream': stream,
        'config': {
            'name': info.config.name,
            'subjects': list(info.config.subjects) if info.config.subjects else [],
            'retention': str(info.config.retention) if info.config.retention else None,
            'max_msgs': info.config.max_msgs,
            'max_bytes': info.config.max_bytes,
            'max_age': info.config.max_age,
        },
        'state': {
            'messages': info.state.messages,
            'bytes': info.state.bytes,
            'first_seq': info.state.first_seq,
            'last_seq': info.state.last_seq,
            'consumer_count': info.state.consumer_count,
        },
    }


# Operation dispatch table
OPERATIONS = {
    'kv_get': _execute_kv_get,
    'kv_put': _execute_kv_put,
    'kv_delete': _execute_kv_delete,
    'kv_keys': _execute_kv_keys,
    'kv_purge': _execute_kv_purge,
    'object_get': _execute_object_get,
    'object_put': _execute_object_put,
    'object_delete': _execute_object_delete,
    'object_list': _execute_object_list,
    'object_info': _execute_object_info,
    'js_publish': _execute_js_publish,
    'js_get_msg': _execute_js_get_msg,
    'js_stream_info': _execute_js_stream_info,
}


def execute_nats_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Optional[Dict[str, Any]] = None,
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a NATS tool task.

    Args:
        task_config: Task configuration from DSL
        context: Execution context
        jinja_env: Jinja2 environment
        task_with: Rendered 'with' parameters
        log_event_callback: Optional callback for logging

    Returns:
        Task execution result

    Example playbook usage:
        tool:
          kind: nats
          auth: nats_credential
          operation: kv_get
          bucket: my_bucket
          key: my_key
    """
    task_with = task_with or {}

    # Resolve auth
    task_config, task_with = resolve_nats_auth(task_config, task_with, jinja_env, context)

    # Get operation
    operation = task_config.get('operation') or task_with.get('operation')
    if not operation:
        raise ValueError("NATS task requires 'operation' field")

    if operation not in OPERATIONS:
        raise ValueError(
            f"Unknown NATS operation: {operation}. "
            f"Valid operations: {', '.join(OPERATIONS.keys())}"
        )

    # Get connection params
    conn_params = get_nats_connection_params(task_with)

    # Build operation kwargs from task_config and task_with
    op_kwargs = {}

    # Common fields
    for field in ['bucket', 'key', 'value', 'ttl', 'pattern', 'name', 'data',
                  'encoding', 'description', 'stream', 'subject', 'headers',
                  'seq', 'last']:
        val = task_config.get(field) or task_with.get(field)
        if val is not None:
            # Render templates
            if isinstance(val, str) and '{{' in val:
                val = render_template(jinja_env, val, context)
            op_kwargs[field] = val

    # Run async operation
    async def _run():
        nc = None
        try:
            nc = await _get_nats_client(conn_params)
            op_func = OPERATIONS[operation]
            result = await op_func(nc, **op_kwargs)
            return result
        finally:
            if nc:
                await nc.close()

    return asyncio.get_event_loop().run_until_complete(_run())
