"""
Common action utilities for NoETL worker plugins.
"""

import os
import requests
from typing import Dict, Any
from noetl.core.logger import setup_logger

logger = setup_logger(__name__)


def report_event(event_data: Dict[str, Any], server_url: str = None) -> None:
    """
    Report an event to the NoETL server.

    Args:
        event_data: Event data to report
        server_url: Server URL (defaults to environment variable)
    """
    try:
        if not server_url:
            server_url = os.environ.get("NOETL_SERVER_URL", "http://localhost:8082")
            if not server_url.endswith('/api'):
                server_url = server_url.rstrip('/') + '/api'

        response = requests.post(
            f"{server_url}/events",
            json=event_data,
            timeout=10
        )

        if response.status_code != 200:
            logger.warning(f"Failed to report event: {response.status_code} - {response.text}")

    except Exception as e:
        logger.error(f"Failed to report event: {e}")


def sql_split(sql: str) -> list:
    """
    Split SQL statements.

    Args:
        sql: SQL string to split

    Returns:
        List of SQL statements
    """
    # Simple SQL splitting - can be enhanced later
    statements = []
    for stmt in sql.split(';'):
        stmt = stmt.strip()
        if stmt:
            statements.append(stmt)
    return statements
