"""
Broker class module (renamed from core.py).

This is a lightweight client used primarily by server code paths; most
server-side orchestration now runs through the event-driven evaluator in
`noetl.api.event.processing`.
"""

from __future__ import annotations

import os
from typing import Any
import httpx
from noetl.core.logger import setup_logger


logger = setup_logger(__name__, include_location=True)


class Broker:
    def __init__(self, agent: Any, server_url: str | None = None):
        self.agent = agent
        base_url = server_url or os.environ.get("NOETL_SERVER_URL", "http://localhost:8082")
        if base_url and not (base_url.startswith("http://") or base_url.startswith("https://")):
            base_url = "http://" + base_url
        if base_url and not base_url.rstrip("/").endswith("/api"):
            base_url = base_url.rstrip("/") + "/api"
        self.server_url = base_url
        self.event_reporting_enabled = True
        # lineage helpers used when running in-process
        self._execution_start_event_id = None
        self._current_step_event_id = None
        self._last_task_start_event_id = None
        self._last_step_complete_event_id = None
        self.validate_server_url()

    def validate_server_url(self) -> None:
        if not self.server_url:
            logger.warning("No server URL provided, disabling event reporting")
            self.event_reporting_enabled = False
            return
        try:
            with httpx.Client(timeout=2.0) as client:
                try:
                    response = client.get(f"{self.server_url}/health", timeout=2.0)
                    response.raise_for_status()
                    logger.info(f"Server at {self.server_url} is reachable")
                except httpx.HTTPStatusError:
                    response = client.get(self.server_url, timeout=2.0)
                    response.raise_for_status()
                    logger.info(f"Server at {self.server_url} is reachable (no health endpoint)")
        except Exception as e:
            logger.warning(f"Server at {self.server_url} is not reachable: {e}")
            logger.warning("Disabling event reporting to prevent hanging")
            self.event_reporting_enabled = False
