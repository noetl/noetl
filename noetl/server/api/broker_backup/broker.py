"""
Broker class module (renamed from core.py).

This is a lightweight client used primarily by server code paths; most
server-side orchestration now runs through the event-driven evaluator in
`noetl.api.event.processing`.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
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
        # workflow state management
        self._workflow_state = {}
        self._default_tables_config = {}
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

    def default_tables(self, tables_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Configure default tables for the workflow execution.

        Args:
            tables_config: Optional dictionary containing table configurations

        Returns:
            Dictionary of default table configurations
        """
        if tables_config is not None:
            self._default_tables_config.update(tables_config)
            logger.info(f"Updated default tables configuration: {list(tables_config.keys())}")

        return self._default_tables_config.copy()

    def transition(self, from_step: str, to_step: str, condition: Optional[str] = None) -> bool:
        """
        Manage workflow step transitions.

        Args:
            from_step: Source step identifier
            to_step: Target step identifier
            condition: Optional transition condition

        Returns:
            Boolean indicating if transition was successful
        """
        try:
            transition_key = f"{from_step}->{to_step}"
            transition_data = {
                "from": from_step,
                "to": to_step,
                "condition": condition,
                "timestamp": None  # Would be set during actual execution
            }

            if "transitions" not in self._workflow_state:
                self._workflow_state["transitions"] = {}

            self._workflow_state["transitions"][transition_key] = transition_data
            logger.info(f"Registered transition: {transition_key}")

            return True
        except Exception as e:
            logger.error(f"Failed to register transition {from_step}->{to_step}: {e}")
            return False

    def workflow(self, steps: Optional[List[Dict[str, Any]]] = None, **kwargs) -> Dict[str, Any]:
        """
        Execute or configure workflow with given steps.

        Args:
            steps: List of workflow step definitions
            **kwargs: Additional workflow configuration parameters

        Returns:
            Dictionary containing workflow execution status and results
        """
        try:
            workflow_config = {
                "steps": steps or [],
                "config": kwargs,
                "status": "initialized",
                "results": {}
            }

            self._workflow_state.update(workflow_config)

            if steps:
                logger.info(f"Configured workflow with {len(steps)} steps")
                for i, step in enumerate(steps):
                    step_name = step.get("name", f"step_{i}")
                    logger.debug(f"Step {i}: {step_name}")

            # If server is available, could send workflow configuration
            if self.event_reporting_enabled and self.server_url:
                self._send_workflow_config(workflow_config)

            return {
                "status": "success",
                "workflow_id": kwargs.get("workflow_id", "default"),
                "steps_count": len(steps) if steps else 0,
                "config": workflow_config
            }

        except Exception as e:
            logger.error(f"Failed to configure workflow: {e}")
            return {
                "status": "error",
                "error": str(e),
                "workflow_id": kwargs.get("workflow_id", "default")
            }

    def _send_workflow_config(self, workflow_config: Dict[str, Any]) -> None:
        """
        Send workflow configuration to server if available.

        Args:
            workflow_config: Workflow configuration dictionary
        """
        try:
            if not self.server_url:
                return

            with httpx.Client(timeout=5.0) as client:
                response = client.post(
                    f"{self.server_url}/workflow/config",
                    json=workflow_config,
                    timeout=5.0
                )
                response.raise_for_status()
                logger.debug("Workflow configuration sent to server successfully")

        except Exception as e:
            logger.warning(f"Failed to send workflow configuration to server: {e}")

    def get_workflow_state(self) -> Dict[str, Any]:
        """Get current workflow state."""
        return self._workflow_state.copy()

    def reset_workflow_state(self) -> None:
        """Reset workflow state to initial state."""
        self._workflow_state.clear()
        self._default_tables_config.clear()
        logger.info("Workflow state reset")
