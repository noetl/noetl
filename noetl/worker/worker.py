import asyncio
import contextlib
import datetime
import json
import os
import signal
import socket
import sys
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

import httpx
from jinja2 import BaseLoader, Environment, StrictUndefined

from noetl.core.common import convert_snowflake_ids_for_api
from noetl.core.config import (
    Settings,
    WorkerSettings,
    get_settings,
    get_worker_settings,
)
from noetl.core.logger import setup_logger
from noetl.core.status import validate_status

logger = setup_logger(__name__, include_location=True)


def _resolve_server_settings(settings: Optional[Settings] = None) -> Settings:
    return settings or get_settings()


def _resolve_worker_settings(
    settings: Optional[WorkerSettings] = None,
) -> WorkerSettings:
    return settings or get_worker_settings()


class TaskExecutionError(RuntimeError):
    """Exception raised when a task execution fails with error status.

    Carries the full result dict to enable retry policy evaluation based on
    result fields like status_code, data, etc.
    """

    def __init__(self, message: str, result: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.result = result or {}


def _normalize_server_url(url: Optional[str], ensure_api: bool = True) -> str:
    """Ensure server URL has http(s) scheme and optional '/api' suffix."""
    try:
        base = (url or "").strip()
        if not base:
            base = "http://localhost:8082"
        if not (base.startswith("http://") or base.startswith("https://")):
            base = "http://" + base
        base = base.rstrip("/")
        if ensure_api and not base.endswith("/api"):
            base = base + "/api"
        return base
    except Exception:
        return "http://localhost:8082/api" if ensure_api else "http://localhost:8082"


def register_server_from_env(settings: Optional[Settings] = None) -> None:
    """Register this server instance with the server registry using settings configuration.

    Uses centralized settings from noetl.core.config instead of direct environment access.
    Settings provide: server_api_url, server_name, server_labels, hostname
    """
    try:
        settings = _resolve_server_settings(settings)

        payload = {
            "name": settings.server_name or f"server-{settings.hostname}",
            "component_type": "server_api",
            "runtime": "server",
            "base_url": settings.server_api_url,
            "status": "ready",
            "capacity": None,
            "labels": settings.server_labels or None,
            "pid": os.getpid(),
            "hostname": settings.hostname,
        }
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(settings.endpoint_runtime_register, json=payload)
                if resp.status_code == 200:
                    logger.info(
                        f"Server registered: {payload['name']} -> {settings.server_api_url}"
                    )
                    try:
                        with open("/tmp/noetl_server_name", "w") as f:
                            f.write(payload["name"])
                    except (IOError, OSError, PermissionError) as e:
                        logger.warning(
                            f"Could not write server name to /tmp/noetl_server_name: {e}"
                        )
                else:
                    logger.warning(
                        f"Server register failed ({resp.status_code}): {resp.text}"
                    )
        except Exception as e:
            logger.warning(f"Server register exception: {e}")
    except Exception:
        logger.exception("Unexpected error during server registration")


def deregister_server_from_env(settings: Optional[Settings] = None) -> None:
    """Deregister server using stored name via HTTP (no DB fallback).

    Uses centralized settings from noetl.core.config for server_api_url and server_name.
    """
    try:
        settings = _resolve_server_settings(settings)
        name: Optional[str] = None
        if os.path.exists("/tmp/noetl_server_name"):
            try:
                with open("/tmp/noetl_server_name", "r") as f:
                    name = f.read().strip()
            except Exception:
                name = None
        if not name:
            name = settings.server_name
        if not name:
            return

        try:
            resp = httpx.request(
                "DELETE",
                settings.endpoint_runtime_deregister,
                json={"name": name, "component_type": "server_api"},
                timeout=5.0,
            )
            logger.info(f"Server deregister response: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.exception(f"Server deregister HTTP error: {e}")

        try:
            os.remove("/tmp/noetl_server_name")
        except FileNotFoundError:
            pass  # Expected if file doesn't exist
        except Exception as e:
            logger.exception(f"Failed to remove server name file: {e}")
        logger.info(f"Deregistered server: {name}")
    except Exception as e:
        logger.exception(f"Server deregistration exception details: {e}")


def register_worker_pool_from_env(
    worker_settings: Optional[WorkerSettings] = None,
) -> None:
    """Register this worker pool with the server registry using worker settings.

    Uses centralized settings from noetl.core.config.WorkerSettings for all configuration:
    - pool_runtime, resolved_pool_name, worker_base_url
    - server_api_url, worker_capacity, worker_labels
    - hostname, namespace
    """
    try:
        worker_settings = _resolve_worker_settings(worker_settings)

        # Generate worker URI based on environment (k8s or local)
        if worker_settings.namespace:
            # Running in Kubernetes
            worker_uri = f"k8s://{worker_settings.namespace}/{worker_settings.hostname}"
        else:
            # Running locally
            worker_uri = f"local://{worker_settings.hostname}"

        payload = {
            "name": worker_settings.resolved_pool_name,
            "runtime": worker_settings.pool_runtime,
            "uri": worker_uri,
            "status": "ready",
            "capacity": worker_settings.worker_capacity,
            "labels": worker_settings.worker_labels or None,
            "pid": os.getpid(),
            "hostname": worker_settings.hostname,
        }

        logger.info(
            f"Registering worker pool '{worker_settings.resolved_pool_name}' with runtime '{worker_settings.pool_runtime}' at {worker_settings.endpoint_worker_pool_register}"
        )

        with httpx.Client(timeout=10.0) as client:  # Increased timeout
            resp = client.post(
                worker_settings.endpoint_worker_pool_register, json=payload
            )
            if resp.status_code == 200:
                logger.info(
                    f"Worker pool registered: {payload['name']} ({payload['runtime']}) -> {payload['uri']}"
                )
                with open(f"/tmp/noetl_worker_pool_name_{payload['name']}", "w") as f:
                    f.write(payload["name"])
            else:
                logger.warning(
                    f"Worker pool register failed ({resp.status_code}): {resp.text}"
                )
                raise Exception(
                    f"Registration failed with status {resp.status_code}: {resp.text}"
                )

    except Exception as e:
        logger.exception(f"Unexpected error during worker pool registration: {e}")
        raise


def deregister_worker_pool_from_env(
    worker_settings: Optional[WorkerSettings] = None,
) -> None:
    """Attempt to deregister worker pool using stored name (HTTP only).

    Uses centralized settings from noetl.core.config.WorkerSettings for server_api_url and pool_name.
    """
    logger.info("Worker deregistration starting...")
    try:
        worker_settings = _resolve_worker_settings(worker_settings)
        name: Optional[str] = (worker_settings.pool_name or "").strip()

        if name:
            logger.info(f"Using worker name from config: {name}")
            worker_file = f"/tmp/noetl_worker_pool_name_{name}"
            if os.path.exists(worker_file):
                with open(worker_file, "r") as f:
                    name = f.read().strip()
                logger.info(f"Found worker name from file: {name}")

        if not name:
            logger.warning("No worker name found for deregistration")
            return

        logger.info(
            f"Attempting to deregister worker {name} via {worker_settings.endpoint_worker_pool_deregister}"
        )

        resp = httpx.request(
            "DELETE",
            worker_settings.endpoint_worker_pool_deregister,
            json={"name": name},
            timeout=5.0,
        )
        logger.info(f"Worker deregister response: {resp.status_code} - {resp.text}")

        worker_file = f"/tmp/noetl_worker_pool_name_{name}"
        if os.path.exists(worker_file):
            os.remove(worker_file)
            logger.info("Removed worker-specific name file")
        elif os.path.exists("/tmp/noetl_worker_pool_name"):
            os.remove("/tmp/noetl_worker_pool_name")
            logger.info("Removed legacy worker name file")
        logger.info(f"Deregistered worker pool: {name}")
    except Exception as e:
        logger.exception(f"Worker deregister general error: {e}")


def on_worker_terminate(signum):
    logger.info(f"Worker pool process received signal {signum}")
    try:
        worker_settings = _resolve_worker_settings()
        retries = worker_settings.deregister_retries
        backoff_base = worker_settings.deregister_backoff
        for attempt in range(1, retries + 1):
            try:
                logger.info(f"Worker deregister attempt {attempt}")
                deregister_worker_pool_from_env(worker_settings)
                logger.info(f"Worker: deregister succeeded (attempt {attempt})")
                break
            except Exception as e:
                logger.error(f"Worker: deregister attempt {attempt} failed: {e}")
            if attempt < retries:
                time.sleep(backoff_base * (2 ** (attempt - 1)))
    finally:
        logger.info("Worker termination signal handler completed")
        sys.exit(1)


def _get_server_url() -> str:
    worker_settings = _resolve_worker_settings()
    return worker_settings.server_api_url


# ------------------------------------------------------------------
# Queue worker pool
# ------------------------------------------------------------------


class QueueWorker:
    """Async worker that polls the server queue API for actions."""

    def __init__(
        self,
        server_url: Optional[str] = None,
        worker_id: Optional[str] = None,
        thread_pool: Optional[ThreadPoolExecutor] = None,
        process_pool: Optional[ProcessPoolExecutor] = None,
        deregister_on_exit: bool = True,
        register_on_init: bool = True,
        settings: Optional[WorkerSettings] = None,
    ) -> None:
        self._settings = _resolve_worker_settings(settings)

        resolved_server_url = server_url or self._settings.normalized_server_url
        self.server_url = _normalize_server_url(resolved_server_url, ensure_api=True)
        self.worker_id = worker_id or self._settings.worker_id or str(uuid.uuid4())
        self._jinja = Environment(loader=BaseLoader(), undefined=StrictUndefined)
        self._thread_pool = thread_pool or ThreadPoolExecutor(max_workers=4)
        self._process_pool = process_pool or ProcessPoolExecutor()
        self._deregister_on_exit = deregister_on_exit
        if register_on_init:
            self._register_pool()

    # ------------------------------------------------------------------
    # Queue interaction helpers
    # ------------------------------------------------------------------

    def _validate_event_status(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and ensure event status is properly normalized before sending."""
        try:
            status = event_data.get("status")
            if status:
                # This will raise ValueError if status is invalid
                validated_status = validate_status(status)
                event_data["status"] = validated_status
            return event_data
        except ValueError as e:
            logger.error(f"Invalid status in event: {e}. Event: {event_data}")
            # This will stop execution as required - show valid statuses in error
            raise ValueError(
                f"Worker generated invalid event status. Must be one of: STARTED, RUNNING, PAUSED, PENDING, FAILED, COMPLETED. {str(e)}"
            )

    def _register_pool(self) -> None:
        """Best-effort registration of this worker pool."""
        try:
            register_worker_pool_from_env(self._settings)
        except Exception:  # pragma: no cover - best effort
            logger.debug("Worker registration failed", exc_info=True)

    async def _lease_job(self, lease_seconds: int = 60) -> Optional[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    self._settings.endpoint_queue_lease,
                    json={"worker_id": self.worker_id, "lease_seconds": lease_seconds},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") == "ok":
                    return data.get("job")
                return None
        except Exception:
            logger.debug("Failed to lease job", exc_info=True)
            return None

    async def _complete_job(self, queue_id: int) -> None:
        try:
            logger.debug(f"WORKER: Completing job {queue_id}")
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    self._settings.endpoint_queue_complete_by_id(queue_id)
                )
        except Exception:  # pragma: no cover - network best effort
            logger.debug("Failed to complete job %s", queue_id, exc_info=True)

    async def _fail_job(
        self,
        queue_id: int,
        should_retry: bool = False,
        retry_delay_seconds: int = 60,
        job: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Mark job as failed with retry policy.

        Args:
            queue_id: Queue ID
            should_retry: Whether to retry the job based on retry policy evaluation
            retry_delay_seconds: Delay before retry in seconds
            job: Job dictionary for emitting retry event
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    self._settings.endpoint_queue_fail_by_id(queue_id),
                    json={
                        "retry": should_retry,
                        "retry_delay_seconds": retry_delay_seconds,
                    },
                )

            # Emit action_retry event if retrying
            if should_retry and job:
                try:
                    execution_id = job.get("execution_id")
                    node_id = job.get("node_id")
                    context = job.get("context") or {}
                    if isinstance(context, str):
                        import json

                        try:
                            context = json.loads(context)
                        except:
                            context = {}

                    # Get attempts from job or queue
                    attempts = job.get("attempts", 0)
                    max_attempts = job.get("max_attempts", 3)

                    retry_event = {
                        "execution_id": execution_id,
                        "event_type": "action_retry",
                        "status": "RUNNING",
                        "node_id": node_id,
                        "node_name": context.get("step_name"),
                        "node_type": "step",
                        "result": {
                            "attempt": attempts,
                            "max_attempts": max_attempts,
                            "retry_delay_seconds": retry_delay_seconds,
                            "message": f"Retrying after failure (attempt {attempts}/{max_attempts})",
                        },
                    }

                    from noetl.plugin import report_event

                    report_event(retry_event, self.server_url)
                    logger.info(
                        f"Emitted action_retry event for job {queue_id}, attempt {attempts}/{max_attempts}"
                    )
                except Exception as e:
                    logger.exception(f"Failed to emit action_retry event: {e}")

        except Exception as e:  # pragma: no cover - network best effort
            logger.exception(f"Failed to mark job {queue_id} failed: {e}")

    async def _evaluate_retry_policy(
        self, job: Dict[str, Any], error: Optional[Exception] = None
    ) -> tuple[bool, int]:
        """
        Evaluate retry policy based on job configuration.

        Args:
            job: Job dictionary with action config and queue metadata
            error: Exception that caused the failure

        Returns:
            Tuple of (should_retry, retry_delay_seconds)
        """
        try:
            # Extract action config
            action_cfg_raw = job.get("action")
            action_cfg = None

            if isinstance(action_cfg_raw, str):
                try:
                    action_cfg = json.loads(action_cfg_raw)
                except json.JSONDecodeError as e:
                    logger.error(
                        f"Failed to parse action config for retry evaluation: {e}"
                    )
                    return (False, 60)
            elif isinstance(action_cfg_raw, dict):
                action_cfg = action_cfg_raw

            if not isinstance(action_cfg, dict):
                return (False, 60)

            # Check if retry is configured
            retry_config = action_cfg.get("retry")
            if not retry_config:
                # No retry configured
                return (False, 60)

            # Parse retry configuration
            if isinstance(retry_config, bool):
                if not retry_config:
                    return (False, 60)
                # Use defaults
                retry_config = {}
            elif isinstance(retry_config, int):
                # Max attempts only
                retry_config = {"max_attempts": retry_config}
            elif not isinstance(retry_config, dict):
                logger.error(f"Invalid retry configuration type: {type(retry_config)}")
                return (False, 60)

            # Get current attempt info
            current_attempts = job.get("attempts", 0)
            max_attempts = job.get("max_attempts", retry_config.get("max_attempts", 3))

            # Check if we've exceeded max attempts
            # Don't retry if we've already used all attempts
            if current_attempts >= max_attempts:
                logger.info(
                    f"Max retry attempts ({max_attempts}) reached for job {job.get('queue_id')} (current attempts: {current_attempts})"
                )
                return (False, 60)

            # Next attempt number for logging and delay calculation
            attempt_number = current_attempts + 1

            # Import retry policy evaluator
            from jinja2 import Environment

            from noetl.plugin.runtime import RetryPolicy

            # Create Jinja2 environment for condition evaluation
            jinja_env = Environment()

            # Create retry policy
            policy = RetryPolicy(retry_config, jinja_env)

            # Build result context for evaluation
            # Extract result data from TaskExecutionError if available
            result = {}
            if isinstance(error, TaskExecutionError) and hasattr(error, "result"):
                # Use the result from the exception which contains full execution result
                result = error.result or {}
                # Extract status_code from data if present
                if "data" in result and isinstance(result["data"], dict):
                    if "status_code" in result["data"]:
                        result["status_code"] = result["data"]["status_code"]

            # Fallback: try to get result from job context
            if not result:
                context = job.get("context") or job.get("input_context") or {}
                if isinstance(context, str):
                    try:
                        context = json.loads(context)
                    except:
                        context = {}

                result = {
                    "error": str(error) if error else None,
                    "success": False,
                    "status": "error",
                    "data": context.get("result")
                    if isinstance(context, dict)
                    else None,
                }

            # Evaluate retry policy
            should_retry = policy.should_retry(result, attempt_number, error)

            # Calculate delay if retrying
            if should_retry:
                delay = policy.get_delay(attempt_number)
                retry_delay_seconds = int(delay)
                logger.info(
                    f"Retry policy evaluation for job {job.get('queue_id')}: "
                    f"retry={should_retry}, delay={retry_delay_seconds}s, "
                    f"attempt={attempt_number}/{max_attempts}"
                )
            else:
                retry_delay_seconds = 60
                logger.info(
                    f"Retry policy evaluation for job {job.get('queue_id')}: "
                    f"retry={should_retry}, attempt={attempt_number}/{max_attempts}"
                )

            return (should_retry, retry_delay_seconds)

        except Exception as e:
            logger.warning(f"Error evaluating retry policy: {e}", exc_info=True)
            # Default to no retry on evaluation error
            return (False, 60)

    # ------------------------------------------------------------------
    # Job execution
    # ------------------------------------------------------------------
    def _execute_job_sync(self, job: Dict[str, Any]) -> None:
        action_cfg_raw = job.get("action")
        raw_context = job.get("context") or job.get("input_context") or {}
        # Server-side rendering: call server to render input context and task config
        # Worker must not render locally; prefer server-evaluated values
        context = raw_context
        rendered_task = None
        try:
            payload = {
                "execution_id": job.get("execution_id"),
                "template": {"work": raw_context, "task": action_cfg_raw},
                "extra_context": {
                    "env": dict(self._settings.raw_env),
                    "job": {
                        "id": job.get("queue_id"),
                        # Provide uuid alias for templates expecting {{ job.uuid }}
                        "uuid": str(job.get("queue_id"))
                        if job.get("queue_id") is not None
                        else None,
                        "execution_id": job.get("execution_id"),
                        "node_id": job.get("node_id"),
                        "worker_id": self.worker_id,
                    },
                },
                "strict": True,
            }
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(f"{self.server_url}/context/render", json=payload)
                if resp.status_code == 200:
                    rend = resp.json().get("rendered")
                    # Expecting a dict { work: <ctx>, task: <resolved_task> }
                    if isinstance(rend, dict):
                        if "work" in rend:
                            context = rend.get("work") or raw_context
                        # Capture server-resolved task config when provided
                        if "task" in rend:
                            rendered_task = rend.get("task")
                    elif isinstance(rend, dict):
                        context = rend
                else:
                    logger.warning(
                        f"WORKER: server render failed {resp.status_code}: {resp.text}"
                    )
        except Exception:
            logger.exception("WORKER: server-side render exception; using raw context")
            context = raw_context
        execution_id = job.get("execution_id")
        catalog_id = job.get("catalog_id")

        # Catalog ID Resolution Chain (defense-in-depth):
        # 1. Job record from queue table (set by QueueService.enqueue_job)
        # 2. Context metadata (legacy/backward compatibility)
        # 3. Server lookup by execution_id (final fallback to prevent event failures)

        # Fallback 1: get catalog_id from context if not present in job
        if not catalog_id:
            try:
                catalog_id = (
                    context.get("catalog_id") if isinstance(context, dict) else None
                )
            except (AttributeError, TypeError, KeyError) as e:
                logger.debug(f"Could not extract catalog_id from context: {e}")

        # Fallback 2: fetch catalog_id from server by execution_id (final defense)
        # This prevents event emission failures and lost telemetry
        if not catalog_id and execution_id:
            try:
                logger.debug(
                    f"WORKER: catalog_id missing, fetching from server for execution {execution_id}"
                )
                with httpx.Client(timeout=5.0) as client:
                    resp = client.get(
                        self._settings.endpoint_events,
                        params={"execution_id": execution_id, "limit": 1},
                    )
                    if resp.status_code == 200:
                        events_data = resp.json()
                        if isinstance(events_data, dict) and events_data.get("events"):
                            first_event = events_data["events"][0]
                            if isinstance(first_event, dict):
                                catalog_id = first_event.get("catalog_id")
                                if catalog_id:
                                    logger.info(
                                        f"WORKER: Retrieved catalog_id {catalog_id} from server for execution {execution_id}"
                                    )
            except Exception as e:
                logger.warning(f"WORKER: Failed to fetch catalog_id from server: {e}")

        node_id = job.get("node_id") or f"job_{job.get('id')}"

        # If server returned a rendered task, use it; otherwise parse raw.
        # Fallback: if rendered is not a dict, try parsing raw JSON.
        action_cfg = None
        original_task_cfg = action_cfg_raw if isinstance(action_cfg_raw, dict) else None
        if rendered_task is not None and isinstance(rendered_task, dict):
            action_cfg = rendered_task
        else:
            if isinstance(action_cfg_raw, str):
                try:
                    action_cfg = json.loads(action_cfg_raw)
                except json.JSONDecodeError:
                    logger.error(
                        f"Failed to parse action config for job {job.get('id')}: {action_cfg_raw}"
                    )
                    return
            elif isinstance(action_cfg_raw, dict):
                action_cfg = action_cfg_raw

        try:
            # Base64 decoding is now handled in individual task executors
            # to ensure single method of code/command handling

            # Original task config merging logic (only when original_task_cfg exists)
            if isinstance(action_cfg, dict) and original_task_cfg:
                placeholder_codes = {"", "def main(**kwargs):\n    return {}"}
                orig_tool = original_task_cfg.get("tool")
                rendered_tool = action_cfg.get("tool")
                orig_tool_norm = str(orig_tool).strip().lower() if orig_tool else None
                rendered_tool_norm = (
                    str(rendered_tool).strip().lower() if rendered_tool else None
                )

                if (
                    orig_tool
                    and (rendered_tool_norm in (None, "", "python"))
                    and (orig_tool_norm not in (None, "", "python"))
                ):
                    action_cfg["tool"] = orig_tool
                elif rendered_tool:
                    action_cfg["tool"] = rendered_tool
                elif orig_tool:
                    action_cfg["tool"] = orig_tool
                action_cfg.pop("type", None)
                if "code" in original_task_cfg:
                    rendered_code = action_cfg.get("code")
                    if (
                        rendered_code in placeholder_codes
                        or "code" not in action_cfg
                        or (
                            isinstance(rendered_code, str)
                            and "{{" in rendered_code
                            and "}}" in rendered_code
                        )
                    ):
                        action_cfg["code"] = original_task_cfg["code"]
                for field in ("command", "commands"):
                    if field in original_task_cfg:
                        rendered_value = action_cfg.get(field)
                        if (
                            field not in action_cfg
                            or not rendered_value
                            or (
                                isinstance(rendered_value, str)
                                and "{{" in rendered_value
                                and "}}" in rendered_value
                            )
                        ):
                            action_cfg[field] = original_task_cfg[field]
                if isinstance(original_task_cfg.get("with"), dict):
                    merged_with = {}
                    merged_with.update(original_task_cfg.get("with") or {})
                    if isinstance(action_cfg.get("with"), dict):
                        merged_with.update(action_cfg.get("with") or {})
                    action_cfg["with"] = merged_with
        except Exception:
            logger.debug(
                "WORKER: Failed to merge original task config after server render",
                exc_info=True,
            )

        if isinstance(action_cfg, dict):
            # Handle broker/maintenance jobs that are not standard task executions
            act_tool = action_cfg.get("tool")
            if not isinstance(act_tool, str) or not act_tool.strip():
                raise ValueError(
                    "Task configuration must include a non-empty 'tool' field"
                )
            act_type = act_tool.strip().lower()

            # Defensive: treat router as non-actionable; complete immediately
            if act_type in ("router", "start"):
                logger.info(
                    f"WORKER: Skipping non-actionable job of type '{act_type}' for node {node_id}"
                )
                from noetl.plugin import report_event

                # Emit minimal started/completed pair for trace consistency
                start_event = {
                    "execution_id": execution_id,
                    "catalog_id": catalog_id,
                    "event_type": "action_started",
                    "status": "RUNNING",
                    "node_id": node_id,
                    "node_name": action_cfg.get("name") or node_id,
                    "node_type": "task",
                    "context": {"work": context, "task": action_cfg},
                }
                start_response = report_event(
                    self._validate_event_status(start_event), self.server_url
                )
                parent_eid = (
                    start_response.get("event_id")
                    if isinstance(start_response, dict)
                    else None
                )
                complete_event = {
                    "execution_id": execution_id,
                    "catalog_id": catalog_id,
                    "event_type": "action_completed",
                    "status": "SUCCEEDED",
                    "node_id": node_id,
                    "node_name": action_cfg.get("name") or node_id,
                    "node_type": "task",
                    "parent_event_id": parent_eid,
                    "context": {"result": {"skipped": True, "reason": "router"}},
                }
                report_event(
                    self._validate_event_status(complete_event), self.server_url
                )
                return

            if act_type == "result_aggregation":
                # Process loop result aggregation job via worker-side coroutine
                import asyncio as _a

                from noetl.plugin.controller.result import process_loop_aggregation_job

                try:
                    _a.run(
                        process_loop_aggregation_job(job)
                    )  # Python >=3.11 has asyncio.run alias
                except Exception:
                    # Compatible run for various environments
                    try:
                        _a.run(process_loop_aggregation_job(job))
                    except Exception:
                        loop = _a.new_event_loop()
                        try:
                            _a.set_event_loop(loop)
                            loop.run_until_complete(process_loop_aggregation_job(job))
                        finally:
                            try:
                                loop.close()
                            except Exception:
                                pass
                # Do not emit separate start/complete events here; the aggregation job emits its own
                return

            task_name = action_cfg.get("name") or node_id

            # Extract step name from context for event node_name (orchestration)
            # Priority: context.step_name > node_id extraction > task_name
            event_node_name = task_name  # Default to task name
            try:
                if isinstance(context, dict) and context.get("step_name"):
                    event_node_name = context["step_name"]
                elif ":" in node_id:
                    event_node_name = node_id.split(":", 1)[1]
            except (KeyError, TypeError, AttributeError, IndexError) as e:
                logger.debug(f"Could not extract step name from context/node_id: {e}")

            logger.debug(
                f"WORKER: raw input_context: {json.dumps(raw_context, default=str)[:500]}"
            )
            try:
                if not isinstance(action_cfg.get("with"), dict):
                    action_cfg["with"] = {}
            except (TypeError, AttributeError, KeyError) as e:
                logger.warning(
                    f"Could not validate/initialize action_cfg 'with' field: {e}"
                )
                raise

            try:
                logger.debug(
                    f"WORKER: evaluated input_context (server): {json.dumps(context, default=str)[:500]}"
                )
            except Exception:
                logger.debug(
                    "WORKER: evaluated input_context not JSON-serializable; using str()"
                )
                logger.debug(
                    f"WORKER: evaluated input_context (str): {str(context)[:500]}"
                )
            loop_meta = None
            try:
                if isinstance(context, dict) and isinstance(context.get("_loop"), dict):
                    lm = context.get("_loop")
                    loop_meta = {
                        "loop_id": lm.get("loop_id"),
                        "loop_name": lm.get("loop_name"),
                        "iterator": lm.get("iterator"),
                        "current_index": lm.get("current_index"),
                        "current_item": lm.get("current_item"),
                        "items_count": lm.get("items_count"),
                    }
            except Exception:
                loop_meta = None

            # Extract parent_event_id and parent_execution_id from queue meta or context
            parent_event_id = None
            parent_execution_id = None
            job_meta = None

            # First priority: check queue meta (set by server when enqueueing)
            try:
                job_meta = job.get("meta")
                if isinstance(job_meta, dict):
                    parent_event_id = job_meta.get("parent_event_id")
                    parent_execution_id = job_meta.get("parent_execution_id")
                elif isinstance(job_meta, str):
                    # meta might be JSON string
                    job_meta_parsed = json.loads(job_meta)
                    if isinstance(job_meta_parsed, dict):
                        job_meta = job_meta_parsed  # Update to parsed dict
                        parent_event_id = job_meta_parsed.get("parent_event_id")
                        parent_execution_id = job_meta_parsed.get("parent_execution_id")
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.debug(f"Could not parse job metadata JSON: {e}")

            # Second priority: check context metadata (legacy/backward compat)
            if not parent_event_id:
                try:
                    if isinstance(context, dict):
                        ctx_meta = context.get("noetl_meta") or {}
                        if isinstance(ctx_meta, dict):
                            peid = ctx_meta.get("parent_event_id")
                            if peid:
                                parent_event_id = peid
                            pexec_id = ctx_meta.get("parent_execution_id")
                            if pexec_id:
                                parent_execution_id = pexec_id
                except (KeyError, TypeError, AttributeError) as e:
                    logger.debug(f"Could not extract parent metadata from context: {e}")

            # Determine node_type for events (iterator vs task)
            node_type_val = "iterator" if act_type == "iterator" else "task"

            # Warn if catalog_id is missing but continue execution
            if not catalog_id:
                logger.warning(
                    f"WORKER: catalog_id is missing for job {job.get('id')} execution {execution_id}. Events may fail to be recorded."
                )

            # Extract retry metadata from queue entry
            attempt_number = job.get("attempts", 0) + 1  # Current attempt (1-indexed)
            max_attempts = job.get("max_attempts", 1)
            is_retry = attempt_number > 1

            start_event = {
                "execution_id": execution_id,
                "catalog_id": catalog_id,
                "event_type": "action_started",
                "status": "RUNNING",
                "node_id": node_id,
                "node_name": event_node_name,  # Use step name for orchestration
                "node_type": node_type_val,
                "context": {
                    "work": context,
                    "task": action_cfg,
                    "retry": {
                        "attempt": attempt_number,
                        "max_attempts": max_attempts,
                        "is_retry": is_retry,
                    },
                },
                "trace_component": {"worker_raw_context": raw_context},
            }
            # Attach queue meta to event for server-side context tracking
            if job_meta and isinstance(job_meta, dict):
                if "meta" not in start_event:
                    start_event["meta"] = {}
                start_event["meta"]["queue_meta"] = job_meta

            if loop_meta:
                start_event.update(loop_meta)
            if parent_event_id:
                start_event["parent_event_id"] = parent_event_id
            if parent_execution_id:
                start_event["parent_execution_id"] = parent_execution_id

            from noetl.plugin import report_event

            start_event = self._validate_event_status(start_event)
            start_response = report_event(start_event, self.server_url)

            # Capture the action_started event_id for use as parent in step_result
            action_started_event_id = None
            try:
                if isinstance(start_response, dict):
                    action_started_event_id = start_response.get("event_id")
            except (TypeError, AttributeError, KeyError) as e:
                logger.debug(f"Could not extract event_id from start_response: {e}")

            try:
                # Normalize payloads: canonical 'args' with legacy aliases
                # DSL Design:
                # - args: inputs TO a step (parameters)
                # - data: outputs FROM a step (results, never on task config)
                # - with/payload/input: legacy aliases for args
                task_data = {}
                if isinstance(action_cfg, dict):
                    # Start from explicit args first
                    if isinstance(action_cfg.get("args"), dict):
                        task_data.update(action_cfg.get("args"))
                    # Merge legacy aliases with precedence: input > payload > with > data (migration)
                    try:
                        w = (
                            action_cfg.get("with")
                            if isinstance(action_cfg.get("with"), dict)
                            else None
                        )
                        if w:
                            task_data = {**w, **task_data}
                    except (TypeError, AttributeError, KeyError) as e:
                        logger.warning(
                            f"Could not merge 'with' field into task_data: {e}"
                        )
                    try:
                        p = (
                            action_cfg.get("payload")
                            if isinstance(action_cfg.get("payload"), dict)
                            else None
                        )
                        if p:
                            task_data = {**p, **task_data}
                    except (TypeError, AttributeError, KeyError) as e:
                        logger.warning(
                            f"Could not merge 'payload' field into task_data: {e}"
                        )
                    try:
                        i = (
                            action_cfg.get("input")
                            if isinstance(action_cfg.get("input"), dict)
                            else None
                        )
                        if i:
                            task_data = {**i, **task_data}
                    except (TypeError, AttributeError, KeyError) as e:
                        logger.warning(
                            f"Could not merge 'input' field into task_data: {e}"
                        )
                    # Migration support: also read from 'data' if present and no 'args'
                    # TODO: Remove after migration period
                    try:
                        if isinstance(
                            action_cfg.get("data"), dict
                        ) and not action_cfg.get("args"):
                            task_data = {**action_cfg.get("data"), **task_data}
                    except (TypeError, AttributeError, KeyError) as e:
                        logger.debug(
                            f"Could not merge 'data' field into task_data (migration path): {e}"
                        )
                if not isinstance(task_data, dict):
                    task_data = {}
                try:
                    exec_ctx = dict(context) if isinstance(context, dict) else {}
                except (TypeError, ValueError) as e:
                    logger.warning(
                        f"Could not convert context to dict, using empty dict: {e}"
                    )
                    exec_ctx = {}
                # Expose unified payload under exec_ctx['input'] for template convenience
                try:
                    if isinstance(exec_ctx, dict):
                        exec_ctx["input"] = dict(task_data)
                        exec_ctx["data"] = dict(task_data)
                except (TypeError, ValueError) as e:
                    logger.warning(f"Could not set input/data in exec_ctx: {e}")
                # Flatten work.workload to top-level workload for template convenience
                try:
                    if isinstance(exec_ctx.get("work"), dict) and isinstance(
                        exec_ctx["work"].get("workload"), dict
                    ):
                        exec_ctx["workload"] = exec_ctx["work"]["workload"]
                except (TypeError, AttributeError, KeyError) as e:
                    logger.debug(f"Could not flatten workload to exec_ctx: {e}")
                try:
                    # Ensure execution_id is present and non-empty in context
                    if not exec_ctx.get("execution_id"):
                        exec_ctx["execution_id"] = execution_id
                except (TypeError, AttributeError) as e:
                    logger.warning(f"Could not set execution_id in exec_ctx: {e}")
                try:
                    if "env" not in exec_ctx:
                        exec_ctx["env"] = dict(self._settings.raw_env)
                except (TypeError, AttributeError, ValueError) as e:
                    logger.warning(f"Could not set env in exec_ctx: {e}")
                try:
                    if "job" not in exec_ctx:
                        exec_ctx["job"] = {
                            "id": job.get("id"),
                            "uuid": str(job.get("id"))
                            if job.get("id") is not None
                            else None,
                            "execution_id": job.get("execution_id"),
                            "node_id": node_id,
                            "worker_id": self.worker_id,
                        }
                except (TypeError, AttributeError, KeyError) as e:
                    logger.warning(f"Could not set job metadata in exec_ctx: {e}")

                import time

                from noetl.plugin import execute_task

                action_start_time = time.time()
                result = execute_task(
                    action_cfg, task_name, exec_ctx, self._jinja, task_data
                )
                action_end_time = time.time()
                action_duration = action_end_time - action_start_time

                # Inline save: if the action config declares a `save` block, perform the save on worker
                inline_save = None
                try:
                    inline_save = (
                        action_cfg.get("save") if isinstance(action_cfg, dict) else None
                    )
                except Exception:
                    inline_save = None
                if inline_save:
                    try:
                        # Provide current result to rendering context as `this` for convenience
                        try:
                            exec_ctx_with_result = dict(exec_ctx)
                            # Provide current step output as 'result' for inline save templates
                            _current = (
                                result.get("data")
                                if isinstance(result, dict)
                                and result.get("data") is not None
                                else result
                            )
                            exec_ctx_with_result["result"] = _current
                            # Back-compat aliases
                            exec_ctx_with_result["this"] = result
                            if "data" not in exec_ctx_with_result:
                                exec_ctx_with_result["data"] = _current
                            logger.debug(
                                f"WORKER: Added result context variables - result keys: {list(_current.keys()) if isinstance(_current, dict) else type(_current)}, this keys: {list(result.keys()) if isinstance(result, dict) else type(result)}"
                            )
                        except Exception as ctx_err:
                            logger.exception(
                                f"WORKER: Failed to add result context variables, falling back to original context: {ctx_err}"
                            )
                            exec_ctx_with_result = exec_ctx
                        from noetl.plugin.shared.storage import (
                            execute_save_task as _do_save,
                        )

                        save_payload = {"save": inline_save}
                        logger.debug(
                            f"WORKER: About to call save plugin with context keys: {list(exec_ctx_with_result.keys()) if isinstance(exec_ctx_with_result, dict) else type(exec_ctx_with_result)}"
                        )
                        if (
                            isinstance(exec_ctx_with_result, dict)
                            and "result" in exec_ctx_with_result
                        ):
                            logger.debug(
                                f"WORKER: Context has 'result' of type: {type(exec_ctx_with_result['result'])}"
                            )
                        save_out = _do_save(
                            save_payload, exec_ctx_with_result, self._jinja, task_data
                        )
                        # Attach save outcome to result envelope under meta.save or data.save
                        if isinstance(result, dict):
                            if "meta" in result and isinstance(result["meta"], dict):
                                result["meta"]["save"] = save_out
                            else:
                                # Keep envelope valid; prefer adding under meta
                                result["meta"] = {"save": save_out}
                    except Exception as _e:
                        # Attach error under meta.save_error but do not fail the action
                        logger.exception("WORKER: Inline save operation failed")
                        if isinstance(result, dict):
                            if "meta" in result and isinstance(result["meta"], dict):
                                result["meta"]["save_error"] = str(_e)
                            else:
                                result["meta"] = {"save_error": str(_e)}

                res_status = (
                    (result or {}).get("status", "") if isinstance(result, dict) else ""
                )
                emitted_error = False
                if isinstance(res_status, str) and res_status.lower() == "error":
                    err_msg = (
                        (result or {}).get("error")
                        if isinstance(result, dict)
                        else "Unknown error"
                    )
                    tb_text = ""
                    if isinstance(result, dict):
                        tb_text = result.get("traceback") or ""
                    error_event = {
                        "execution_id": execution_id,
                        "catalog_id": catalog_id,
                        "event_type": "action_failed",
                        "status": "FAILED",
                        "node_id": node_id,
                        "node_name": event_node_name,  # Use step name for orchestration
                        "node_type": node_type_val,
                        "duration": action_duration,
                        "error": err_msg,
                        "stack_trace": tb_text,
                        "result": result,
                    }
                    # Attach queue meta to event for server-side context tracking
                    if job_meta and isinstance(job_meta, dict):
                        if "meta" not in error_event:
                            error_event["meta"] = {}
                        error_event["meta"]["queue_meta"] = job_meta

                    if loop_meta:
                        error_event.update(loop_meta)
                    if parent_event_id:
                        error_event["parent_event_id"] = parent_event_id
                    if parent_execution_id:
                        error_event["parent_execution_id"] = parent_execution_id

                    from noetl.plugin import report_event

                    error_event = self._validate_event_status(error_event)
                    report_event(error_event, self.server_url)
                    emitted_error = True
                    raise TaskExecutionError(
                        err_msg or "Task returned error status", result=result
                    )
                else:
                    complete_event = {
                        "execution_id": execution_id,
                        "catalog_id": catalog_id,
                        "event_type": "action_completed",
                        "status": "COMPLETED",
                        "node_id": node_id,
                        "node_name": event_node_name,  # Use step name for orchestration
                        "node_type": node_type_val,
                        "duration": action_duration,
                        "result": result,
                    }
                    # Attach queue meta to event for server-side context tracking
                    if job_meta and isinstance(job_meta, dict):
                        if "meta" not in complete_event:
                            complete_event["meta"] = {}
                        complete_event["meta"]["queue_meta"] = job_meta

                    if loop_meta:
                        complete_event.update(loop_meta)
                    # Use action_started event_id as parent for action_completed
                    if action_started_event_id:
                        complete_event["parent_event_id"] = action_started_event_id
                    elif parent_event_id:
                        # Fallback to context parent_event_id for iterator/nested cases
                        complete_event["parent_event_id"] = parent_event_id
                    if parent_execution_id:
                        complete_event["parent_execution_id"] = parent_execution_id

                    from noetl.plugin import report_event

                    complete_event = self._validate_event_status(complete_event)
                    report_event(complete_event, self.server_url)

                    # Emit a companion step_result event for easier querying of results per step
                    try:
                        norm_result = result
                        if (
                            isinstance(result, dict)
                            and "data" in result
                            and result["data"] is not None
                        ):
                            norm_result = result["data"]
                        step_result_event = {
                            "execution_id": execution_id,
                            "catalog_id": catalog_id,
                            "event_type": "step_result",
                            "status": "COMPLETED",
                            "node_id": node_id,
                            "node_name": event_node_name,  # Use step name for orchestration
                            "node_type": node_type_val,
                            "duration": action_duration,
                            "result": norm_result,
                        }
                        # Attach queue meta to event for server-side context tracking
                        if job_meta and isinstance(job_meta, dict):
                            if "meta" not in step_result_event:
                                step_result_event["meta"] = {}
                            step_result_event["meta"]["queue_meta"] = job_meta

                        if loop_meta:
                            step_result_event.update(loop_meta)

                        # FIX: Use action_started event_id as parent, not context parent_event_id
                        # The context parent_event_id might incorrectly point to next step's step_started
                        if action_started_event_id:
                            step_result_event["parent_event_id"] = (
                                action_started_event_id
                            )
                        elif parent_event_id:
                            # Fallback to context parent_event_id for iterator/nested cases
                            step_result_event["parent_event_id"] = parent_event_id
                        if parent_execution_id:
                            step_result_event["parent_execution_id"] = (
                                parent_execution_id
                            )

                        from noetl.plugin import report_event

                        step_result_event = self._validate_event_status(
                            step_result_event
                        )
                        report_event(step_result_event, self.server_url)
                    except Exception:
                        logger.debug(
                            "WORKER: Failed to emit step_result companion event",
                            exc_info=True,
                        )

            except Exception as e:
                logger.exception(f"WORKER: Exception during task execution for job {e}")
                try:
                    import traceback as _tb

                    tb_text = _tb.format_exc()
                except Exception:
                    tb_text = str(e)
                if not locals().get("emitted_error"):
                    error_event = {
                        "execution_id": execution_id,
                        "catalog_id": catalog_id,
                        "event_type": "action_failed",
                        "status": "FAILED",
                        "node_id": node_id,
                        "node_name": task_name,
                        "node_type": node_type_val,
                        "error": f"{type(e).__name__}: {str(e)}",
                        "stack_trace": tb_text,
                        "result": {"error": str(e), "stack_trace": tb_text},
                    }
                    # Add duration if action_duration was captured (error during/after execute_task)
                    if "action_duration" in locals():
                        error_event["duration"] = action_duration
                    # Attach queue meta to event for server-side context tracking
                    if job_meta and isinstance(job_meta, dict):
                        if "meta" not in error_event:
                            error_event["meta"] = {}
                        error_event["meta"]["queue_meta"] = job_meta

                    if loop_meta:
                        error_event.update(loop_meta)
                    if parent_event_id:
                        error_event["parent_event_id"] = parent_event_id
                    if parent_execution_id:
                        error_event["parent_execution_id"] = parent_execution_id

                    from noetl.plugin import report_event

                    error_event = self._validate_event_status(error_event)
                    report_event(error_event, self.server_url)
                raise  # Re-raise to let the worker handle job failure
        else:
            logger.warning(
                "Job %s has no actionable configuration", str(job.get("queue_id"))
            )

    async def _execute_job(self, job: Dict[str, Any]) -> None:
        loop = asyncio.get_running_loop()
        use_process = bool(job.get("run_mode") == "process")
        executor = self._process_pool if use_process else self._thread_pool
        try:
            await loop.run_in_executor(executor, self._execute_job_sync, job)
            await self._complete_job(job["queue_id"])
        except Exception as exc:
            logger.exception("Error executing job %s: %s", job.get("queue_id"), exc)

            # Evaluate retry policy if configured in the job
            should_retry, retry_delay = await self._evaluate_retry_policy(job, exc)
            await self._fail_job(job["queue_id"], should_retry, retry_delay, job)

    # ------------------------------------------------------------------
    async def _report_simple_worker_metrics(self) -> None:
        """Report simple worker metrics for standalone QueueWorker instances."""
        # Check if metrics are disabled
        metrics_disabled = self._settings.metrics_disabled
        if metrics_disabled:
            # logger.debug("Simple metric reporting disabled")
            return

        try:
            import psutil

            # Basic system metrics for standalone worker
            metrics_data = []

            try:
                # CPU and memory
                cpu_percent = psutil.cpu_percent(interval=0.1)
                memory = psutil.virtual_memory()
                process = psutil.Process()

                metrics_data.extend(
                    [
                        {
                            "metric_name": "noetl_system_cpu_usage_percent",
                            "metric_type": "gauge",
                            "metric_value": cpu_percent,
                            "help_text": "CPU usage percentage",
                            "unit": "percent",
                        },
                        {
                            "metric_name": "noetl_system_memory_usage_percent",
                            "metric_type": "gauge",
                            "metric_value": memory.percent,
                            "help_text": "Memory usage percentage",
                            "unit": "percent",
                        },
                        {
                            "metric_name": "noetl_worker_status",
                            "metric_type": "gauge",
                            "metric_value": 1,  # 1 = active
                            "help_text": "Worker status (1=active, 0=inactive)",
                            "unit": "status",
                        },
                    ]
                )
            except Exception as e:
                logger.debug(f"Error collecting worker metrics: {e}")

            # Get component name from environment or use worker_id
            component_name = (
                self._settings.pool_name or ""
            ).strip() or f"worker-{self.worker_id}"

            # Report to server
            payload = {
                "component_name": component_name,
                "component_type": "queue_worker",
                "metrics": [
                    {
                        "metric_name": m.get("metric_name", ""),
                        "metric_type": m.get("metric_type", "gauge"),
                        "metric_value": m.get("metric_value", 0),
                        "labels": {
                            "component": component_name,
                            "worker_id": self.worker_id,
                            "hostname": self._settings.hostname,
                        },
                        "help_text": m.get("help_text", ""),
                        "unit": m.get("unit", ""),
                    }
                    for m in metrics_data
                ],
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.server_url}/metrics/report", json=payload
                )
                if resp.status_code != 200:
                    logger.debug(
                        f"Worker metrics report failed {resp.status_code}: {resp.text}"
                    )

        except Exception as e:
            logger.debug(f"Failed to report worker metrics: {e}")

    # ------------------------------------------------------------------
    async def run_forever(
        self, interval: float = 1.0, stop_event: Optional[asyncio.Event] = None
    ) -> None:
        """Continuously poll for jobs and execute them asynchronously.

        Parameters
        ----------
        interval:
            Sleep duration between lease attempts when the queue is empty.
        stop_event:
            Optional :class:`asyncio.Event` that can be set by the caller to
            request the loop to exit.  This makes the worker usable inside
            pools where individual workers need to be stopped or replaced
            dynamically.
        """
        # Metrics reporting interval (default 60 seconds)
        metrics_interval = self._settings.worker_metrics_interval
        last_metrics_time = 0.0

        try:
            while True:
                if stop_event and stop_event.is_set():
                    break

                current_time = time.time()

                # Report metrics periodically
                if current_time - last_metrics_time >= metrics_interval:
                    try:
                        await self._report_simple_worker_metrics()
                        last_metrics_time = current_time
                    except Exception:
                        logger.debug("Worker metrics reporting failed", exc_info=True)

                job = await self._lease_job()
                if job:
                    await self._execute_job(job)
                else:
                    await asyncio.sleep(interval)
        finally:
            if self._deregister_on_exit:
                try:
                    await asyncio.to_thread(deregister_worker_pool_from_env)
                except Exception as e:
                    logger.error(
                        f"Failed to deregister worker pool on exit: {e}", exc_info=True
                    )


class ScalableQueueWorkerPool:
    """Pool that scales worker tasks based on queue depth."""

    def __init__(
        self,
        server_url: Optional[str] = None,
        max_workers: Optional[int] = None,
        check_interval: float = 5.0,
        worker_poll_interval: float = 1.0,
        max_processes: Optional[int] = None,
        settings: Optional[WorkerSettings] = None,
    ) -> None:
        self._settings = _resolve_worker_settings(settings)
        resolved_server_url = server_url or self._settings.normalized_server_url
        self.server_url = _normalize_server_url(resolved_server_url, ensure_api=True)
        self.max_workers = max_workers or self._settings.max_workers
        self.check_interval = check_interval
        self.worker_poll_interval = worker_poll_interval
        self.max_processes = max_processes or self.max_workers
        self.worker_id = self._settings.worker_id or str(uuid.uuid4())
        self._thread_pool = ThreadPoolExecutor(max_workers=self.max_workers)
        self._process_pool = ProcessPoolExecutor(max_workers=self.max_processes)
        self._tasks: List[Tuple[asyncio.Task, asyncio.Event]] = []
        self._stop = asyncio.Event()
        self._stopped = False

    # --------------------------------------------------------------
    async def _queue_size(self) -> int:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(self._settings.endpoint_queue_size)
                resp.raise_for_status()
                data = resp.json()
                return int(data.get("queued") or data.get("count") or 0)
        except Exception:  # pragma: no cover - network best effort
            logger.debug("Failed fetching queue size", exc_info=True)
            return 0

    def _spawn_worker(self) -> None:
        stop_evt = asyncio.Event()
        worker = QueueWorker(
            self.server_url,
            thread_pool=self._thread_pool,
            process_pool=self._process_pool,
            deregister_on_exit=False,
            register_on_init=False,
            settings=self._settings,
        )
        task = asyncio.create_task(
            worker.run_forever(self.worker_poll_interval, stop_evt)
        )
        self._tasks.append((task, stop_evt))

    async def _report_worker_metrics(self, component_name: str) -> None:
        """Report worker metrics to the server."""
        # Check if metrics are disabled
        metrics_disabled = self._settings.metrics_disabled
        if metrics_disabled:
            logger.debug(f"Metric reporting disabled for {component_name}")
            return

        try:
            # Import here to avoid circular imports
            import psutil

            # Collect system metrics locally (based on metrics.py)
            metrics_data = []

            try:
                # CPU usage
                cpu_percent = psutil.cpu_percent(interval=0.1)
                metrics_data.append(
                    {
                        "metric_name": "noetl_system_cpu_usage_percent",
                        "metric_type": "gauge",
                        "metric_value": cpu_percent,
                        "help_text": "CPU usage percentage",
                        "unit": "percent",
                    }
                )

                # Memory usage
                memory = psutil.virtual_memory()
                metrics_data.append(
                    {
                        "metric_name": "noetl_system_memory_usage_bytes",
                        "metric_type": "gauge",
                        "metric_value": memory.used,
                        "help_text": "Memory usage in bytes",
                        "unit": "bytes",
                    }
                )

                metrics_data.append(
                    {
                        "metric_name": "noetl_system_memory_usage_percent",
                        "metric_type": "gauge",
                        "metric_value": memory.percent,
                        "help_text": "Memory usage percentage",
                        "unit": "percent",
                    }
                )

                # Process info
                process = psutil.Process()
                metrics_data.append(
                    {
                        "metric_name": "noetl_process_cpu_percent",
                        "metric_type": "gauge",
                        "metric_value": process.cpu_percent(),
                        "help_text": "Process CPU usage percentage",
                        "unit": "percent",
                    }
                )

                memory_info = process.memory_info()
                metrics_data.append(
                    {
                        "metric_name": "noetl_process_memory_rss_bytes",
                        "metric_type": "gauge",
                        "metric_value": memory_info.rss,
                        "help_text": "Process RSS memory in bytes",
                        "unit": "bytes",
                    }
                )

            except Exception as e:
                logger.debug(f"Error collecting system metrics: {e}")

            # Add worker-specific metrics
            metrics_data.extend(
                [
                    {
                        "metric_name": "noetl_worker_active_tasks",
                        "metric_type": "gauge",
                        "metric_value": len(self._tasks),
                        "help_text": "Number of active worker tasks",
                        "unit": "tasks",
                    },
                    {
                        "metric_name": "noetl_worker_max_workers",
                        "metric_type": "gauge",
                        "metric_value": self.max_workers,
                        "help_text": "Maximum configured workers",
                        "unit": "workers",
                    },
                    {
                        "metric_name": "noetl_worker_queue_size",
                        "metric_type": "gauge",
                        "metric_value": await self._queue_size(),
                        "help_text": "Current queue size",
                        "unit": "jobs",
                    },
                ]
            )

            # Report to server
            payload = {
                "component_name": component_name,
                "component_type": "worker_pool",
                "metrics": [
                    {
                        "metric_name": m.get("metric_name", ""),
                        "metric_type": m.get("metric_type", "gauge"),
                        "metric_value": m.get("metric_value", 0),
                        "labels": {
                            "component": component_name,
                            "worker_id": self.worker_id,
                            "hostname": self._settings.hostname,
                        },
                        "help_text": m.get("help_text", ""),
                        "unit": m.get("unit", ""),
                    }
                    for m in metrics_data
                ],
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.server_url}/metrics/report", json=payload
                )
                if resp.status_code != 200:
                    logger.debug(
                        f"Metrics report failed {resp.status_code}: {resp.text}"
                    )

        except Exception as e:
            logger.debug(f"Failed to report worker metrics: {e}")

    async def _scale_workers(self) -> None:
        desired = min(self.max_workers, max(1, await self._queue_size()))
        current = len(self._tasks)
        if desired > current:
            for _ in range(desired - current):
                self._spawn_worker()
        elif desired < current:
            for _ in range(current - desired):
                task, evt = self._tasks.pop()
                evt.set()
                await task

    # --------------------------------------------------------------
    async def run_forever(self) -> None:
        """Run the auto-scaling loop until ``stop`` is called."""
        # Ensure single registration for the pool
        registration_success = False
        try:
            register_worker_pool_from_env(self._settings)
            registration_success = True
            logger.info("Worker pool registration completed successfully")
        except Exception as e:
            logger.warning(f"Pool initial registration failed: {e}")

        # Retry registration if it failed
        if not registration_success:
            logger.info("Retrying worker pool registration...")
            try:
                register_worker_pool_from_env(self._settings)
                logger.info("Worker pool registration retry succeeded")
            except Exception as e:
                logger.error(f"Worker pool registration retry failed: {e}")

        # Heartbeat loop task
        heartbeat_interval = self._settings.worker_heartbeat_interval

        async def _heartbeat_loop():
            name = (self._settings.pool_name or "").strip() or "worker-cpu"
            payload = {"name": name}
            url = self._settings.endpoint_worker_pool_heartbeat
            consecutive_failures = 0
            max_failures = 5

            while not self._stop.is_set():
                try:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        resp = await client.post(url, json=payload)
                        if resp.status_code != 200:
                            logger.warning(
                                f"Worker heartbeat non-200 {resp.status_code}: {resp.text}"
                            )
                            consecutive_failures += 1
                        else:
                            consecutive_failures = 0

                    # Report metrics with heartbeat (if enabled)
                    if not self._settings.metrics_disabled:
                        try:
                            await self._report_worker_metrics(name)
                        except Exception as metrics_error:
                            logger.debug(
                                f"Worker metrics reporting failed: {metrics_error}"
                            )

                except Exception as e:
                    consecutive_failures += 1
                    logger.warning(
                        f"Worker heartbeat failed (attempt {consecutive_failures}/{max_failures}): {e}"
                    )
                    if consecutive_failures >= max_failures:
                        logger.error(
                            f"Worker heartbeat failed {max_failures} consecutive times, still continuing..."
                        )
                        consecutive_failures = 0  # Reset to avoid spam

                await asyncio.sleep(heartbeat_interval)

        hb_task = asyncio.create_task(_heartbeat_loop())
        try:
            while not self._stop.is_set():
                await self._scale_workers()
                await asyncio.sleep(self.check_interval)
        finally:
            await self.stop()
            try:
                hb_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await hb_task
            except Exception as e:
                logger.error(f"Error cancelling heartbeat task: {e}", exc_info=True)

    async def stop(self) -> None:
        """Request the scaling loop and all workers to stop."""
        if self._stopped:
            return
        self._stop.set()
        for task, evt in self._tasks:
            evt.set()
        await asyncio.gather(*(t for t, _ in self._tasks), return_exceptions=True)
        self._tasks.clear()
        self._thread_pool.shutdown(wait=False)
        self._process_pool.shutdown(wait=False)
        self._stopped = True
