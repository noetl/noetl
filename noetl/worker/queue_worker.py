from __future__ import annotations

import asyncio
import json
import uuid
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from typing import Dict, Optional, Any

from jinja2 import BaseLoader, Environment, StrictUndefined
from pydantic import ValidationError

from noetl.core.config import WorkerSettings
from noetl.core.logger import setup_logger
from noetl.core.status import validate_status

from .api_client import WorkerAPIClient
from .errors import TaskExecutionError
from .executors import create_process_pool_executor
from .job_executor import JobExecutor
from .models import QueueJob
from .registry import (
    deregister_worker_pool_from_env,
    register_worker_pool_from_env,
    resolve_worker_settings,
)
from .utils import normalize_server_url

logger = setup_logger(__name__, include_location=True)


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
        allow_process_pool_creation: bool = True,
    ) -> None:
        self._settings = resolve_worker_settings(settings)

        resolved_server_url = server_url or self._settings.normalized_server_url
        self.server_url = normalize_server_url(resolved_server_url, ensure_api=True)
        self.worker_id = worker_id or self._settings.worker_id or str(uuid.uuid4())
        self._jinja = Environment(loader=BaseLoader(), undefined=StrictUndefined)
        self._jinja.filters["tojson"] = lambda value: json.dumps(value, ensure_ascii=False)
        
        # Register token resolution function for OAuth/service account auth
        try:
            from noetl.core.auth.token_resolver import register_token_functions
            register_token_functions(self._jinja, {})
            logger.debug("Registered token resolution functions in Jinja environment")
        except Exception as e:
            logger.warning(f"Failed to register token functions (non-critical): {e}")
        
        self._thread_pool = thread_pool or ThreadPoolExecutor(max_workers=4)
        if process_pool is not None:
            self._process_pool = process_pool
        elif allow_process_pool_creation:
            self._process_pool = create_process_pool_executor()
        else:
            self._process_pool = None
        self._deregister_on_exit = deregister_on_exit
        self._api = WorkerAPIClient(self._settings)
        self._job_executor = JobExecutor(
            self._settings,
            self.worker_id,
            self.server_url,
            self._api,
            self._jinja,
            self._run_action,
        )
        if register_on_init:
            self._register_pool()

    def _register_pool(self) -> None:
        try:
            register_worker_pool_from_env(self._settings)
        except Exception:
            logger.debug("Worker registration failed", exc_info=True)

    async def _lease_job(self, lease_seconds: int = 60) -> Optional[Dict[str, Any]]:
        return await self._api.lease_job(self.worker_id, lease_seconds)

    async def _complete_job(self, queue_id: int) -> None:
        logger.debug("WORKER: Completing job %s", queue_id)
        await self._api.complete_job(queue_id)

    async def _fail_job(
        self,
        queue_id: int,
        should_retry: bool = False,
        retry_delay_seconds: int = 60,
        job: Optional[QueueJob] = None,
    ) -> None:
        await self._api.fail_job(queue_id, should_retry, retry_delay_seconds)

        if should_retry and job:
            try:
                execution_id = job.execution_id
                node_id = job.effective_node_id
                context = job.context
                attempts = job.attempts
                max_attempts = job.max_attempts
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
                await self._emit_worker_event(retry_event)
                logger.info(
                    "Emitted action_retry event for job %s, attempt %s/%s",
                    queue_id,
                    attempts,
                    max_attempts,
                )
            except Exception as exc:
                logger.exception(f"Failed to emit action_retry event: {exc}")

    async def _emit_worker_event(self, event_data: Dict[str, Any]) -> None:
        from noetl.core.runtime import report_event_async

        status = event_data.get("status")
        if status:
            event_data["status"] = validate_status(status)
        await report_event_async(event_data, self.server_url)

    async def _run_action(
        self,
        action_cfg: Dict[str, Any],
        task_name: str,
        exec_ctx: Dict[str, Any],
        task_data: Dict[str, Any],
        use_process: bool,
    ) -> Dict[str, Any]:
        # CRITICAL: Check if loop is in action_cfg
        has_loop = 'loop' in action_cfg
        logger.critical(f"WORKER._run_action: task='{task_name}', has_loop={has_loop}, action_cfg_keys={list(action_cfg.keys())}")
        if has_loop:
            logger.critical(f"WORKER._run_action: loop block = {action_cfg.get('loop')}")
        
        # All tools (including Python) must go through execute_task to support iterator/loop handling
        from noetl.plugin import execute_task
        
        # Create event callback for iterator executor
        # This is a sync function that will be called from the thread pool
        def event_callback(
            event_type: str,
            task_id: str,
            task_name: str,
            task_type: str,
            status: str,
            duration: float,
            context: Dict[str, Any],
            result: Optional[Any],
            event_data: Optional[Dict[str, Any]],
            error: Optional[str]
        ) -> None:
            """Sync callback that bridges to async event emission."""
            import asyncio as async_module
            from noetl.core.runtime import report_event_async
            
            # Build event payload matching server expectations
            # Server uses EventEmitRequest schema which expects specific field names
            payload = {
                'event_type': event_type,
                'execution_id': str(exec_ctx.get('execution_id')),  # Must be string
                'status': status,
                'node_name': task_name,  # Server expects node_name for step/task name
                'node_type': task_type,  # Server expects node_type for task type
                'duration': duration,
                'context': event_data or {},  # Iterator metadata goes in context
                'meta': {
                    'task_id': task_id
                },
                'result': result
            }
            
            if error:
                payload['error'] = error
            
            # Run async event emission in a new event loop
            # This is safe because we're in a thread pool, not the main event loop
            try:
                loop = async_module.new_event_loop()
                async_module.set_event_loop(loop)
                try:
                    loop.run_until_complete(
                        report_event_async(payload, self.server_url)
                    )
                finally:
                    loop.close()
                logger.info(f"WORKER: Emitted {event_type} event via callback")
            except Exception as e:
                logger.error(f"WORKER: Failed to emit {event_type} event: {e}", exc_info=True)

        loop = asyncio.get_running_loop()
        executor = (
            self._process_pool if use_process and self._process_pool else self._thread_pool
        )
        return await loop.run_in_executor(
            executor, execute_task, action_cfg, task_name, exec_ctx, self._jinja, task_data, event_callback
        )

    async def _evaluate_retry_policy(
        self, job: QueueJob, error: Optional[Exception] = None
    ) -> tuple[bool, int]:
        try:
            retry_config = job.action.retry
            if not retry_config:
                return (False, 60)

            if isinstance(retry_config, bool):
                if not retry_config:
                    return (False, 60)
                retry_config = {}
            elif isinstance(retry_config, int):
                retry_config = {"max_attempts": retry_config}
            elif not isinstance(retry_config, dict):
                logger.error("Invalid retry configuration type: %s", type(retry_config))
                return (False, 60)

            current_attempts = job.attempts
            max_attempts = job.max_attempts or retry_config.get("max_attempts", 3)
            if current_attempts >= max_attempts:
                logger.info(
                    "Max retry attempts (%s) reached for job %s (current attempts: %s)",
                    max_attempts,
                    job.queue_id,
                    current_attempts,
                )
                return (False, 60)

            attempt_number = current_attempts + 1

            from jinja2 import Environment
            from noetl.core.runtime import RetryPolicy

            jinja_env = Environment()
            policy = RetryPolicy(retry_config, jinja_env)

            result = {}
            if isinstance(error, TaskExecutionError):
                result = error.result or {}
                if "data" in result and isinstance(result["data"], dict):
                    if "status_code" in result["data"]:
                        result["status_code"] = result["data"]["status_code"]

            if not result:
                context = job.context
                result = {
                    "error": str(error) if error else None,
                    "success": False,
                    "status": "error",
                    "data": context.get("result") if isinstance(context, dict) else None,
                }

            should_retry = policy.should_retry(result, attempt_number, error)
            if should_retry:
                delay = policy.get_delay(attempt_number)
                retry_delay_seconds = int(delay)
                logger.info(
                    "Retry policy evaluation for job %s: retry=%s, delay=%ss, attempt=%s/%s",
                    job.queue_id,
                    should_retry,
                    retry_delay_seconds,
                    attempt_number,
                    max_attempts,
                )
            else:
                retry_delay_seconds = 60
                logger.info(
                    "Retry policy evaluation for job %s: retry=%s, attempt=%s/%s",
                    job.queue_id,
                    should_retry,
                    attempt_number,
                    max_attempts,
                )

            return (should_retry, retry_delay_seconds)
        except Exception as exc:
            logger.exception(f"Error evaluating retry policy: {exc}")
            return (False, 60)

    async def _execute_job(self, job: Dict[str, Any]) -> None:
        queue_id = job.get("queue_id") or job.get("id")
        try:
            job_model = QueueJob.model_validate(job)
        except ValidationError as exc:
            logger.exception(f"Invalid job payload {queue_id}: {exc}")
            if queue_id is not None:
                await self._fail_job(queue_id, should_retry=False, retry_delay_seconds=0)
            return
        except Exception as exc:
            # Catch any other validation errors (TypeError, etc) to prevent worker crash
            logger.exception(f"Unexpected error validating job payload {queue_id}: {exc}")
            if queue_id is not None:
                await self._fail_job(queue_id, should_retry=False, retry_delay_seconds=0)
            return
        try:
            await self._job_executor.run(job_model)
            await self._complete_job(job_model.queue_id)
        except Exception as exc:
            logger.exception(f"Error executing job {job_model.queue_id}: {exc}")
            should_retry, retry_delay = await self._evaluate_retry_policy(job_model, exc)
            await self._fail_job(job_model.queue_id, should_retry, retry_delay, job_model)

    async def run_forever(
        self, interval: float = 1.0, stop_event: Optional[asyncio.Event] = None
    ) -> None:
        try:
            while True:
                if stop_event and stop_event.is_set():
                    break

                job = await self._lease_job()
                if job:
                    await self._execute_job(job)
                else:
                    await asyncio.sleep(interval)
        finally:
            if self._deregister_on_exit:
                try:
                    await asyncio.to_thread(deregister_worker_pool_from_env)
                except Exception as exc:
                    logger.error(
                        "Failed to deregister worker pool on exit: %s", exc, exc_info=True
                    )
