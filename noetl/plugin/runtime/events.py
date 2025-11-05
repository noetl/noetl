"""
Event reporting tool for worker-to-server communication.

Provides functionality for workers to report execution events back to the
NoETL server API with automatic enrichment of worker metadata and tracing.
"""

import os
import socket
import json
import httpx
from decimal import Decimal
from typing import Dict, Any, Optional

from noetl.core.logger import setup_logger
from noetl.core.config import WorkerSettings, get_worker_settings

logger = setup_logger(__name__, include_location=True)

# Module-level worker settings cache for performance
_cached_worker_settings: Optional[WorkerSettings] = None

def _get_worker_settings() -> Optional[WorkerSettings]:
    """
    Get cached worker settings or return None if not available.
    Uses try-except to handle cases where worker settings aren't initialized.
    """
    global _cached_worker_settings
    if _cached_worker_settings is None:
        try:
            _cached_worker_settings = get_worker_settings()
        except Exception:
            # Worker settings not available (e.g., running in server context)
            pass
    return _cached_worker_settings


def _decimal_serializer(obj):
    """
    JSON serializer for objects not serializable by default json code.
    
    Handles:
    - Decimal: Convert to float for JSON serialization
    
    Args:
        obj: Object to serialize
        
    Returns:
        JSON-serializable representation of the object
        
    Raises:
        TypeError: If object type is not handled
    """
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def report_event(event_data: Dict[str, Any], server_url: str) -> Dict[str, Any]:
    """
    Report an event to the NoETL server.
    
    Enriches the event with worker metadata including:
    - Worker pool name and runtime
    - Process ID and hostname
    - Worker ID
    
    Args:
        event_data: Event data to report
        server_url: Base URL of the NoETL server
        
    Returns:
        Response from the server
    """
    # try:
    # Enrich metadata with worker pool/runtime hints
    _enrich_event_metadata(event_data)
    
    # Attach trace component with worker details
    _enrich_trace_component(event_data)
    
    # Build the API URL
    url = _build_event_url(server_url)
    
    logger.debug(f"Reporting event to {url}: {event_data.get('event_type', 'unknown')}")
    
    # Serialize event data with Decimal handling
    json_data = json.dumps(event_data, default=_decimal_serializer)
    
    # Send the event to the server
    with httpx.Client(timeout=10.0) as client:
        response = client.post(
            url, 
            content=json_data,
            headers={"Content-Type": "application/json"}
        )
        # response.raise_for_status()
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Failed to report event, status code: {response.status_code}, response: {response.text}")
            raise RuntimeError(f"Failed to report event, status code: {response.status_code}")

            
    # except Exception as e:
    #     logger.exception(f"Failed to report event: {e}")
    #     return {"status": "error", "message": str(e)}


def _enrich_event_metadata(event_data: Dict[str, Any]) -> None:
    """
    Enrich event metadata with worker pool and runtime information.
    
    Uses centralized WorkerSettings configuration instead of direct os.environ access.
    
    Args:
        event_data: Event data to enrich (modified in place)
    """
    try:
        meta = event_data.get('meta') or {}
        if not isinstance(meta, dict):
            meta = {}
        
        # Try to get worker settings, fallback to os.environ for backwards compatibility
        worker_settings = _get_worker_settings()
        if worker_settings:
            worker_pool = worker_settings.resolved_pool_name
            worker_runtime = worker_settings.pool_runtime
        else:
            # Fallback to environment variables if settings not available
            worker_pool = os.environ.get('NOETL_WORKER_POOL_NAME')
            worker_runtime = os.environ.get('NOETL_WORKER_POOL_RUNTIME')
        
        if worker_pool and not meta.get('worker_pool'):
            meta['worker_pool'] = worker_pool
        if worker_runtime and not meta.get('worker_runtime'):
            meta['worker_runtime'] = worker_runtime
            
        event_data['meta'] = meta
    except Exception:
        logger.exception("Failed to enrich event metadata")
        pass


def _enrich_trace_component(event_data: Dict[str, Any]) -> None:
    """
    Attach trace component with worker details.
    
    Uses centralized WorkerSettings configuration instead of direct os.environ access.
    Adds worker information including pool, runtime, pid, hostname, and id.
    Only sets fields if not already present to avoid overwriting upstream info.
    
    Args:
        event_data: Event data to enrich (modified in place)
    """
    try:
        trace_component = event_data.get('trace_component') or {}
        if not isinstance(trace_component, dict):
            trace_component = {}
            
        worker_tc = trace_component.get('worker') or {}
        if not isinstance(worker_tc, dict):
            worker_tc = {}
        
        # Try to get worker settings, fallback to os.environ for backwards compatibility
        worker_settings = _get_worker_settings()
        if worker_settings:
            worker_pool = worker_settings.resolved_pool_name
            worker_runtime = worker_settings.pool_runtime
            worker_id = worker_settings.worker_id
            hostname = worker_settings.hostname
        else:
            # Fallback to environment variables if settings not available
            worker_pool = os.environ.get('NOETL_WORKER_POOL_NAME')
            worker_runtime = os.environ.get('NOETL_WORKER_POOL_RUNTIME')
            worker_id = os.environ.get('NOETL_WORKER_ID')
            hostname = socket.gethostname()
        
        # Set fields if not already present
        if worker_pool and 'pool' not in worker_tc:
            worker_tc['pool'] = worker_pool
        if worker_runtime and 'runtime' not in worker_tc:
            worker_tc['runtime'] = worker_runtime
        if worker_id and 'id' not in worker_tc:
            worker_tc['id'] = worker_id
        if 'pid' not in worker_tc:
            worker_tc['pid'] = os.getpid()
        if 'hostname' not in worker_tc:
            worker_tc['hostname'] = hostname
            
        trace_component['worker'] = worker_tc
        event_data['trace_component'] = trace_component
    except Exception:
        logger.exception("Failed to enrich trace component")
        pass


def _build_event_url(server_url: str) -> str:
    """
    Build the complete event API URL from the server base URL.
    
    Kept for backward compatibility. For new code, use worker_settings.endpoint_events.
    
    Args:
        server_url: Base URL of the NoETL server
        
    Returns:
        Complete URL to the events API endpoint
    """
    # Handle server_url that may already include /api
    if server_url.endswith('/api'):
        return f"{server_url}/events"
    else:
        return f"{server_url}/api/events"
