"""
Base utilities and common functions for job execution.
"""

import os
import json
import httpx
import datetime
from typing import Dict, Any, Optional
from jinja2 import Environment

from noetl.core.common import DateTimeEncoder, make_serializable
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def report_event(event_data: Dict[str, Any], server_url: str) -> Dict[str, Any]:
    """
    Report an event to the NoETL server.

    Args:
        event_data: Event data to report
        server_url: Base URL of the NoETL server

    Returns:
        Response from the server
    """
    try:
        import httpx
        # Enrich metadata with worker pool/runtime hints
        try:
            import os as _os
            meta = event_data.get('meta') or {}
            if not isinstance(meta, dict):
                meta = {}
            wp = _os.environ.get('NOETL_WORKER_POOL_NAME')
            wr = _os.environ.get('NOETL_WORKER_POOL_RUNTIME')
            if wp and not meta.get('worker_pool'):
                meta['worker_pool'] = wp
            if wr and not meta.get('worker_runtime'):
                meta['worker_runtime'] = wr
            event_data['meta'] = meta
        except Exception:
            pass

        # Attach trace component with worker details (pool, runtime, pid, hostname, id)
        try:
            import os as _os
            import socket as _socket
            tc = event_data.get('trace_component') or {}
            if not isinstance(tc, dict):
                tc = {}
            worker_tc = tc.get('worker') or {}
            if not isinstance(worker_tc, dict):
                worker_tc = {}
            wp = _os.environ.get('NOETL_WORKER_POOL_NAME')
            wr = _os.environ.get('NOETL_WORKER_POOL_RUNTIME')
            wid = _os.environ.get('NOETL_WORKER_ID')
            # Set fields if not already present to avoid overwriting upstream info
            if wp and 'pool' not in worker_tc:
                worker_tc['pool'] = wp
            if wr and 'runtime' not in worker_tc:
                worker_tc['runtime'] = wr
            if wid and 'id' not in worker_tc:
                worker_tc['id'] = wid
            if 'pid' not in worker_tc:
                worker_tc['pid'] = _os.getpid()
            if 'hostname' not in worker_tc:
                worker_tc['hostname'] = _socket.gethostname()
            tc['worker'] = worker_tc
            event_data['trace_component'] = tc
        except Exception:
            pass

        # Handle server_url that may already include /api
        if server_url.endswith('/api'):
            url = f"{server_url}/events"
        else:
            url = f"{server_url}/api/events"
        logger.debug(f"Reporting event to {url}: {event_data.get('event_type', 'unknown')}")

        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=event_data)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.warning(f"Failed to report event: {e}")
        return {"status": "error", "message": str(e)}


def sql_split(sql_text: str) -> list[str]:
    """
    Split SQL text into individual statements.

    Args:
        sql_text: SQL text to split

    Returns:
        List of individual SQL statements
    """
    import re

    # Split on semicolons, but be careful about semicolons in strings
    statements = []
    current_statement = []
    in_string = False
    string_char = None

    for char in sql_text:
        if not in_string and char in ('"', "'"):
            # Enter string literal and keep the quote
            in_string = True
            string_char = char
            current_statement.append(char)
        elif in_string and char == string_char:
            # Exit string literal and keep the quote
            in_string = False
            string_char = None
            current_statement.append(char)
        elif not in_string and char == ';':
            statement = ''.join(current_statement).strip()
            if statement:
                statements.append(statement)
            current_statement = []
        else:
            current_statement.append(char)

    # Add any remaining statement
    remaining = ''.join(current_statement).strip()
    if remaining:
        statements.append(remaining)

    return statements


__all__ = ['report_event', 'sql_split']
