"""
Event reporting tool for worker-to-server communication.

Provides functionality for workers to report execution events back to the
NoETL server API with automatic enrichment of worker metadata and tracing.
"""

import os
import socket
import httpx
from typing import Dict, Any

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


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
    try:
        # Enrich metadata with worker pool/runtime hints
        _enrich_event_metadata(event_data)
        
        # Attach trace component with worker details
        _enrich_trace_component(event_data)
        
        # Build the API URL
        url = _build_event_url(server_url)
        
        logger.debug(f"Reporting event to {url}: {event_data.get('event_type', 'unknown')}")
        
        # Send the event to the server
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=event_data)
            response.raise_for_status()
            return response.json()
            
    except Exception as e:
        logger.warning(f"Failed to report event: {e}")
        return {"status": "error", "message": str(e)}


def _enrich_event_metadata(event_data: Dict[str, Any]) -> None:
    """
    Enrich event metadata with worker pool and runtime information.
    
    Args:
        event_data: Event data to enrich (modified in place)
    """
    try:
        meta = event_data.get('meta') or {}
        if not isinstance(meta, dict):
            meta = {}
            
        worker_pool = os.environ.get('NOETL_WORKER_POOL_NAME')
        worker_runtime = os.environ.get('NOETL_WORKER_POOL_RUNTIME')
        
        if worker_pool and not meta.get('worker_pool'):
            meta['worker_pool'] = worker_pool
        if worker_runtime and not meta.get('worker_runtime'):
            meta['worker_runtime'] = worker_runtime
            
        event_data['meta'] = meta
    except Exception:
        pass


def _enrich_trace_component(event_data: Dict[str, Any]) -> None:
    """
    Attach trace component with worker details.
    
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
            
        # Get worker environment variables
        worker_pool = os.environ.get('NOETL_WORKER_POOL_NAME')
        worker_runtime = os.environ.get('NOETL_WORKER_POOL_RUNTIME')
        worker_id = os.environ.get('NOETL_WORKER_ID')
        
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
            worker_tc['hostname'] = socket.gethostname()
            
        trace_component['worker'] = worker_tc
        event_data['trace_component'] = trace_component
    except Exception:
        pass


def _build_event_url(server_url: str) -> str:
    """
    Build the complete event API URL from the server base URL.
    
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
