from __future__ import annotations

import asyncio
import time
import traceback
from typing import Any, Awaitable, Callable, Dict, Optional, Union

from jinja2 import Environment
from pydantic import BaseModel, ConfigDict, Field

from noetl.core.config import WorkerSettings
from noetl.core.logger import setup_logger
from noetl.core.status import validate_status

from .api_client import WorkerAPIClient
from .errors import TaskExecutionError
from .models import ActionConfig, QueueJob

logger = setup_logger(__name__, include_location=True)

RunAction = Callable[
    [Dict[str, Any], str, Dict[str, Any], Dict[str, Any], bool],
    Awaitable[Dict[str, Any]],
]


class PreparedJob(BaseModel):
    """Normalized job ready for execution and event emission."""

    queue_id: int
    job_id: Optional[int]
    execution_id: str
    catalog_id: str
    node_id: str
    node_name: str
    action_cfg: ActionConfig
    args: Dict[str, Any]
    context: Dict[str, Any]
    raw_context: Dict[str, Any]
    action_type: str
    job_meta: Dict[str, Any] = Field(default_factory=dict)
    parent_event_id: Optional[str] = None
    parent_execution_id: Optional[str] = None
    loop_meta: Dict[str, Any] = Field(default_factory=dict)
    attempts: int = 1
    max_attempts: int = 1
    is_retry: bool = False
    use_process: bool = False

    model_config = ConfigDict(arbitrary_types_allowed=True)


class EventPayload(BaseModel):
    """Structured payload for worker->server event emission."""

    event_type: str
    status: str
    node_type: str
    execution_id: str
    catalog_id: Optional[str] = None
    node_id: Optional[str] = None
    node_name: Optional[str] = None
    duration: Optional[float] = None
    context: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    stack_trace: Optional[str] = None
    trace_component: Optional[Dict[str, Any]] = None
    parent_event_id: Optional[str] = None
    parent_execution_id: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(extra="allow")


class JobExecutor:
    """Handles validation, execution and event reporting for queue jobs."""

    def __init__(
        self,
        settings: WorkerSettings,
        worker_id: str,
        server_url: str,
        api_client: WorkerAPIClient,
        jinja_env: Environment,
        run_action: RunAction,
    ) -> None:
        self._settings = settings
        self._worker_id = worker_id
        self._server_url = server_url
        self._api = api_client
        self._jinja = jinja_env
        self._run_action = run_action

    async def run(self, job: QueueJob) -> None:
        try:
            prepared = await self._prepare_job(job)
        except Exception as exc:
            tb_text = traceback.format_exc()
            await self._emit_prepare_failure(job, exc, tb_text)
            raise

        if prepared.action_type in {"router", "start"}:
            await self._emit_router_events(prepared)
            return

        if prepared.action_type == "result_aggregation":
            from noetl.plugin.controller.result import process_loop_aggregation_job

            await process_loop_aggregation_job(job.model_dump())
            return

        await self._execute_action(prepared)

    async def _prepare_job(self, job: QueueJob) -> PreparedJob:
        action_cfg = await self._render_server_context(job)
        raw_context = dict(job.context)

        job_meta = job.meta or {}
        parent_event_id = job_meta.get("parent_event_id")
        parent_execution_id = job_meta.get("parent_execution_id")

        context_meta = job.context.get("noetl_meta")
        if isinstance(context_meta, dict):
            parent_event_id = parent_event_id or context_meta.get("parent_event_id")
            parent_execution_id = (
                parent_execution_id or context_meta.get("parent_execution_id")
            )

        attempts = job.attempts + 1
        node_name = job.step_name or action_cfg.name or job.effective_node_id

        return PreparedJob(
            queue_id=job.queue_id,
            job_id=job.id,
            execution_id=job.execution_id,
            catalog_id=job.catalog_id,
            node_id=job.effective_node_id,
            node_name=node_name,
            action_cfg=action_cfg,
            args=dict(action_cfg.args),
            context=job.context,
            raw_context=raw_context,
            action_type=action_cfg.tool.lower(),
            job_meta=job_meta,
            parent_event_id=parent_event_id,
            parent_execution_id=parent_execution_id,
            loop_meta=job.loop_metadata(),
            attempts=attempts,
            max_attempts=job.max_attempts,
            is_retry=attempts > 1,
            use_process=job.use_process,
        )

    async def _render_server_context(self, job: QueueJob) -> ActionConfig:
        try:
            payload = {
                "execution_id": job.execution_id,
                "template": {"work": job.context, "task": job.action.model_dump()},
                "extra_context": {
                    "env": dict(self._settings.raw_env),
                    "job": {
                        "id": job.queue_id,
                        "uuid": str(job.queue_id),
                        "execution_id": job.execution_id,
                        "node_id": job.node_id,
                        "worker_id": self._worker_id,
                    },
                },
                "strict": True,
            }
            rendered = await self._api.render_context(payload)
            if isinstance(rendered, dict):
                work_context = rendered.get("work")
                if isinstance(work_context, dict):
                    job.context = work_context
                task_cfg = rendered.get("task")
                if isinstance(task_cfg, dict):
                    return ActionConfig.model_validate(task_cfg)
            return job.action
        except Exception as exc:
            logger.exception(f"Failed to render context on server: {exc}")
            raise RuntimeError("Server-side context rendering failed") from exc

    async def _emit_prepare_failure(
        self, job: QueueJob, exc: Exception, stack_trace: str
    ) -> None:
        event = EventPayload(
            execution_id=job.execution_id,
            catalog_id=job.catalog_id,
            event_type="action_failed",
            status="FAILED",
            node_id=job.effective_node_id,
            node_name=job.step_name or job.effective_node_id,
            node_type=job.context.get("step_type") or "task",
            error=f"{type(exc).__name__}: {exc}",
            stack_trace=stack_trace,
            context={
                "work": job.context,
                "task": job.action.model_dump(),
            },
        )
        await self._emit_event(event)

    async def _emit_router_events(self, prepared: PreparedJob) -> None:
        start_event = self._build_event_payload(
            prepared,
            event_type="action_started",
            status="RUNNING",
            node_type="task",
            context={
                "work": prepared.context,
                "task": prepared.action_cfg.model_dump(),
            },
        )
        start_response = await self._emit_event(start_event)
        parent_event_id = start_response.get("event_id") if isinstance(start_response, dict) else None
        complete_event = self._build_event_payload(
            prepared,
            event_type="action_completed",
            status="COMPLETED",
            node_type="task",
            parent_event_override=parent_event_id,
            context={"result": {"skipped": True, "reason": "router"}},
        )
        await self._emit_event(complete_event)

    async def _execute_action(self, prepared: PreparedJob) -> None:
        node_type = "iterator" if prepared.action_type == "iterator" else "task"
        start_event = self._build_event_payload(
            prepared,
            event_type="action_started",
            status="RUNNING",
            node_type=node_type,
            context={
                "work": prepared.context,
                "task": prepared.action_cfg.model_dump(),
                "retry": {
                    "attempt": prepared.attempts,
                    "max_attempts": prepared.max_attempts,
                    "is_retry": prepared.is_retry,
                },
            },
            trace_component={"worker_raw_context": prepared.raw_context},
        )
        start_response = await self._emit_event(start_event)
        action_started_event_id = None
        if isinstance(start_response, dict):
            action_started_event_id = start_response.get("event_id")

        exec_ctx = self._build_execution_context(prepared)

        emitted_error = False
        action_duration = 0.0
        try:
            action_start_time = time.time()
            result = await self._run_action(
                prepared.action_cfg.model_dump(),
                prepared.node_name,
                exec_ctx,
                prepared.args,
                prepared.use_process,
            )
            action_duration = time.time() - action_start_time
            result = await self._run_inline_save_if_needed(prepared, exec_ctx, result)
            if self._result_indicates_error(result):
                err_msg = self._extract_error_message(result)
                tb_text = self._extract_traceback(result)
                error_event = self._build_error_event(
                    prepared,
                    node_type,
                    action_duration,
                    err_msg,
                    tb_text,
                    result,
                )
                await self._emit_event(error_event)
                emitted_error = True
                raise TaskExecutionError(
                    err_msg or "Task returned error status", result=result
                )

            complete_event = self._build_complete_event(
                prepared,
                node_type,
                action_duration,
                result,
                action_started_event_id,
            )
            await self._emit_event(complete_event)

            await self._emit_step_result(
                prepared,
                node_type,
                action_duration,
                result,
                action_started_event_id,
            )
        except Exception as exc:
            if isinstance(exc, TaskExecutionError):
                raise

            tb_text = traceback.format_exc()
            error_event = self._build_error_event(
                prepared,
                node_type,
                action_duration if action_duration else None,
                f"{type(exc).__name__}: {exc}",
                tb_text,
                {"error": str(exc), "stack_trace": tb_text},
            )
            if not emitted_error:
                await self._emit_event(error_event)
            raise

    def _build_execution_context(self, prepared: PreparedJob) -> Dict[str, Any]:
        try:
            exec_ctx = dict(prepared.context)
        except Exception:
            exec_ctx = {}

        exec_ctx.setdefault("input", dict(prepared.args))
        exec_ctx.setdefault("data", dict(prepared.args))
        exec_ctx.setdefault("env", dict(self._settings.raw_env))
        exec_ctx.setdefault("execution_id", prepared.execution_id)
        exec_ctx.setdefault(
            "job",
            {
                "id": prepared.job_id,
                "uuid": str(prepared.job_id) if prepared.job_id is not None else None,
                "execution_id": prepared.execution_id,
                "node_id": prepared.node_id,
                "worker_id": self._worker_id,
            },
        )
        return exec_ctx

    async def _run_inline_save_if_needed(
        self,
        prepared: PreparedJob,
        exec_ctx: Dict[str, Any],
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        inline_save = prepared.action_cfg.save
        if not inline_save:
            return result

        try:
            exec_ctx_with_result = dict(exec_ctx)
            current_result = (
                result.get("data")
                if isinstance(result, dict) and result.get("data") is not None
                else result
            )
            exec_ctx_with_result["result"] = current_result
            exec_ctx_with_result["this"] = result
            exec_ctx_with_result.setdefault("data", current_result)
        except Exception:
            exec_ctx_with_result = exec_ctx

        from noetl.plugin.shared.storage import execute_save_task as _do_save

        save_payload = {"save": inline_save}
        loop = None
        loop = asyncio.get_running_loop()
        save_out = await loop.run_in_executor(
            None, _do_save, save_payload, exec_ctx_with_result, self._jinja
        )
        if isinstance(result, dict):
            result.setdefault("meta", {})
            result["meta"]["save"] = save_out
        return result

    def _result_indicates_error(self, result: Dict[str, Any]) -> bool:
        if not isinstance(result, dict):
            return False
        status = str(result.get("status") or "").lower()
        if status == "error":
            return True
        meta = result.get("meta")
        if isinstance(meta, dict):
            save_result = meta.get("save")
            if isinstance(save_result, dict):
                return save_result.get("status") == "error"
        return False

    def _extract_error_message(self, result: Dict[str, Any]) -> str:
        if isinstance(result, dict):
            if "error" in result and result["error"]:
                return str(result["error"])
            meta = result.get("meta")
            if isinstance(meta, dict):
                save_result = meta.get("save")
                if isinstance(save_result, dict):
                    return save_result.get("error", "Unknown save error")
        return "Unknown error"

    def _extract_traceback(self, result: Dict[str, Any]) -> str:
        if isinstance(result, dict):
            return str(result.get("traceback") or "")
        return ""

    def _validate_step_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(result, dict):
            raise ValueError(
                f"Step result must be a dictionary, got {type(result).__name__}"
            )
        data = result.get("data")
        if data is not None and not isinstance(data, dict):
            raise ValueError("Step result 'data' field must be a dictionary")
        return data if data is not None else result

    def _extract_step_status(self, result: Dict[str, Any]) -> str:
        if not isinstance(result, dict):
            raise ValueError("Step result must be a dictionary with 'status'")
        raw_status = result.get("status")
        if not isinstance(raw_status, str):
            raise ValueError("Step result must include a string 'status' field")
        upper = raw_status.strip().upper()
        if upper in {"COMPLETED", "FAILED", "RUNNING", "PENDING"}:
            return upper
        legacy_map = {
            "SUCCESS": "COMPLETED",
            "OK": "COMPLETED",
            "ERROR": "FAILED",
            "FAIL": "FAILED",
            "FAILURE": "FAILED",
        }
        if upper in legacy_map:
            return legacy_map[upper]
        raise ValueError(f"Unsupported step result status: {raw_status}")

    def _base_event(self, prepared: PreparedJob) -> Dict[str, Any]:
        event = {
            "execution_id": prepared.execution_id,
            "catalog_id": prepared.catalog_id,
            "node_id": prepared.node_id,
            "node_name": prepared.node_name,
        }
        if prepared.job_meta:
            event.setdefault("meta", {})
            event["meta"]["queue_meta"] = prepared.job_meta
        if prepared.loop_meta:
            event.update(prepared.loop_meta)
        if prepared.parent_event_id:
            event["parent_event_id"] = prepared.parent_event_id
        if prepared.parent_execution_id:
            event["parent_execution_id"] = prepared.parent_execution_id
        return event

    def _build_event_payload(
        self,
        prepared: PreparedJob,
        *,
        event_type: str,
        status: str,
        node_type: str,
        parent_event_override: Optional[str] = None,
        **extra: Any,
    ) -> EventPayload:
        base = self._base_event(prepared)
        if parent_event_override is not None:
            base["parent_event_id"] = parent_event_override
        base.update(
            {
                "event_type": event_type,
                "status": status,
                "node_type": node_type,
            }
        )
        base.update({k: v for k, v in extra.items() if v is not None})
        return EventPayload.model_validate(base)

    def _build_error_event(
        self,
        prepared: PreparedJob,
        node_type: str,
        duration: Optional[float],
        error_message: str,
        stack_trace: str,
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        extra = {
            "result": result,
            "error": error_message,
            "stack_trace": stack_trace,
        }
        if duration is not None:
            extra["duration"] = duration
        return self._build_event_payload(
            prepared,
            event_type="action_failed",
            status="FAILED",
            node_type=node_type,
            **extra,
        )

    def _build_complete_event(
        self,
        prepared: PreparedJob,
        node_type: str,
        duration: float,
        result: Dict[str, Any],
        action_started_event_id: Optional[str],
    ) -> Dict[str, Any]:
        return self._build_event_payload(
            prepared,
            event_type="action_completed",
            status="COMPLETED",
            node_type=node_type,
            duration=duration,
            result=result,
            parent_event_override=action_started_event_id,
        )

    async def _emit_step_result(
        self,
        prepared: PreparedJob,
        node_type: str,
        duration: float,
        result: Dict[str, Any],
        action_started_event_id: Optional[str],
    ) -> None:
        normalized = self._validate_step_result(result)
        status = self._extract_step_status(result)
        event = self._build_event_payload(
            prepared,
            event_type="step_result",
            status=status,
            node_type=node_type,
            duration=duration,
            result=normalized,
            parent_event_override=action_started_event_id or prepared.parent_event_id,
        )
        await self._emit_event(event)

    async def _emit_event(
        self, event_data: Union[Dict[str, Any], EventPayload]
    ) -> Dict[str, Any]:
        from noetl.plugin.runtime import report_event_async

        payload = (
            event_data.model_dump(exclude_none=True)
            if isinstance(event_data, EventPayload)
            else event_data
        )
        status = payload.get("status")
        if status:
            payload["status"] = validate_status(status)
        return await report_event_async(payload, self._server_url)
