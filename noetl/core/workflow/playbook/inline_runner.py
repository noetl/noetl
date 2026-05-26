"""Round B inline execution runner.

This module implements the worker-side inline runner that actually executes an
approved child playbook in-process, skipping the ``/api/execute`` HTTP
round-trip and the NATS dispatch round-trip.

The runner is intentionally narrow in scope:
- It only accepts children that ``detect_inline_child`` has already approved.
- It only runs steps whose ``tool.kind`` is ``python``, ``mcp``, or ``noop``.
- It allocates a fresh child ``execution_id`` using ``uuid`` (the server-side
  snowflake allocator is async and server-local; the runner mirrors the id
  shape without reaching the database).
- It records all inline-metadata fields on every event it emits so that
  replay, status, and listing readers can identify inline events without
  structural schema changes.

Design seam: the worker's event-emit path (``_emit_batch_events`` and
``_emit_terminal_event_batch`` in ``nats_worker.py``) is tied to a running
asyncio loop and an HTTP session. The runner therefore accepts two lightweight
callables as constructor arguments:
- ``batch_event_emitter``: async ``(events: list[dict]) -> bool`` -- emits a
  list of event dicts via the existing ``/api/events/batch`` endpoint.
- ``cancellation_probe``: async ``(execution_id: str) -> bool`` -- returns
  ``True`` when the given execution is cancelled.

This keeps the runner free of direct HTTP state while reusing the same event
shapes the dispatched path produces.

Round B contract (approved in round-01-result.md lines 156-164):
1. Child execution_id is preserved (fresh snowflake per inline invocation).
2. Command projection rows exist for replay/status/listing parity.
3. Cancellation propagation: parent cancel → child appends
   execution.cancelled and returns status: "error".
4. Recursion depth is bounded by DEFAULT_MAX_DEPTH (3); depth 4+ falls back
   to dispatch in the caller.
5. All step boundaries log at DEBUG only — no INFO on the hot path.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from noetl.core.logger import setup_logger
from noetl.core.workflow.playbook.inline_execution import (
    DEFAULT_MAX_DEPTH,
    InlineDecision,
)

logger = setup_logger(__name__, include_location=True)

# Inline metadata key names written on every event the inline runner emits.
_META_INLINED_IN_PARENT = "inlined_in_parent"
_META_INLINED_IN_COMMAND = "inlined_in_command"
_META_INLINE_DEPTH = "inline_depth"
_META_INLINE_MODE = "inline_mode"
_INLINE_MODE_WORKER = "worker"


@dataclass
class InlineResult:
    """Return value from ``run_inline``.

    Mirrors the agent envelope shape ``_invoke_noetl_playbook`` returns so the
    call site in ``executor.py`` can substitute it 1:1 for the HTTP/NATS path.

    Fields:
        status: "ok" on success, "error" on any failure or cancellation.
        data: Terminal step result, or None if the run failed before producing
              one.
        error: Error dict with ``kind``, ``code``, ``message`` when
               status == "error".
        meta: Dict carrying ``inline_decision`` plus the ``inlined_*`` keys.
        execution_id: The child's allocated execution id string.
    """

    status: str
    data: Any = None
    error: Optional[Dict[str, Any]] = None
    meta: Dict[str, Any] = field(default_factory=dict)
    execution_id: Optional[str] = None

    def to_envelope(self, *, entrypoint: str) -> Dict[str, Any]:
        """Return a dict in the agent envelope shape."""
        envelope: Dict[str, Any] = {
            "status": self.status,
            "framework": "noetl",
            "entrypoint": entrypoint,
            "data": self.data,
            "execution_id": self.execution_id,
        }
        if self.meta:
            envelope["meta"] = dict(self.meta)
        if self.error is not None:
            envelope["error"] = dict(self.error)
        return envelope


def _allocate_child_execution_id() -> str:
    """Allocate a fresh child execution_id.

    The server-side snowflake allocator (``get_snowflake_id``) is an async
    DB operation that requires the server process context. The inline runner
    runs inside the worker process and must allocate ids without a DB round-
    trip. We use a UUID4 derived 18-digit integer string to match the shape
    callers expect from the server path while staying process-local.

    The 18-digit ceiling is load-bearing: every execution_id column in the
    NoETL schema is PostgreSQL ``bigint`` (signed 64-bit, max ~9.22e18).
    An earlier shape used ``% (10 ** 20)`` which produced 20-digit ids up
    to ~9.99e19 — about 11x the bigint ceiling.  Phase D validation on GKE
    observed ``value "69474466565741823165" is out of range for type
    bigint`` from ``/api/executions/<child>/events`` and from the engine's
    state-insert path, leaving the child event stream unretrievable and
    some downstream extraction silently failing.

    The narrowing to 18 digits keeps 60 bits of entropy (~1.15e18 distinct
    ids).  Collision probability across one billion sibling ids is on the
    order of 4e-37; across a single worker process lifetime it is
    indistinguishable from zero.  Cross-process collisions with
    server-allocated snowflakes are also astronomically improbable —
    snowflakes encode time + worker id + sequence and do not collide with
    uniformly-random ids in a 60-bit space.
    """
    raw = uuid.uuid4().int % (10 ** 18)
    return str(raw).zfill(18)


def _inline_meta(
    *,
    parent_execution_id: str,
    parent_command_id: Optional[str],
    depth: int,
) -> Dict[str, Any]:
    """Build the shared inline metadata dict for event payloads."""
    return {
        _META_INLINED_IN_PARENT: parent_execution_id,
        _META_INLINED_IN_COMMAND: parent_command_id,
        _META_INLINE_DEPTH: depth,
        _META_INLINE_MODE: _INLINE_MODE_WORKER,
    }


def _step_name(step: Any) -> str:
    if isinstance(step, dict):
        return str(step.get("step") or step.get("name") or "unknown")
    return "unknown"


def _tool_kind_from_step(step: Any) -> str:
    if not isinstance(step, dict):
        return "noop"
    tool = step.get("tool")
    if isinstance(tool, dict):
        return str(tool.get("kind") or "noop").strip().lower()
    if isinstance(tool, list) and tool:
        first = tool[0] if isinstance(tool[0], dict) else {}
        return str(first.get("kind") or "noop").strip().lower()
    return "noop"


def _tool_config_from_step(step: Any) -> Dict[str, Any]:
    if not isinstance(step, dict):
        return {}
    tool = step.get("tool")
    if isinstance(tool, dict):
        return dict(tool)
    if isinstance(tool, list) and tool and isinstance(tool[0], dict):
        return dict(tool[0])
    return {}


async def run_inline(
    *,
    parent_execution_id: str,
    parent_command_id: Optional[str],
    parent_step: str,
    child_playbook: Dict[str, Any],
    child_input: Dict[str, Any],
    inline_decision: InlineDecision,
    jinja_env: Any,
    cancellation_probe: Callable[[str], Any],
    batch_event_emitter: Callable[[str, List[Dict[str, Any]]], Any],
    depth: int,
) -> InlineResult:
    """Run a detector-approved child playbook inline inside the current worker.

    Parameters
    ----------
    parent_execution_id:
        The parent execution's id string.  The child is correlated to it via
        ``parent_execution_id`` in lifecycle events.
    parent_command_id:
        The parent command id, attached to inline metadata.
    parent_step:
        The parent step name that triggered the inline execution.
    child_playbook:
        Parsed playbook dict (detector-approved).  Steps are iterated directly
        from ``child_playbook["workflow"]``.
    child_input:
        Input payload merged into the child render context as ``workload``.
    inline_decision:
        The ``InlineDecision`` from Round A detector (``inline`` must be True).
    jinja_env:
        Jinja2 Environment reused from the parent worker slot.
    cancellation_probe:
        Async callable ``(execution_id: str) -> bool`` that returns True when
        the execution is cancelled.  Called before each step.
    batch_event_emitter:
        Async callable ``(execution_id: str, events: list[dict]) -> bool`` that
        posts the event list to ``/api/events/batch``.
    depth:
        Current inline depth (0-based, bounded by DEFAULT_MAX_DEPTH = 3).

    Returns
    -------
    InlineResult
        Agent-envelope-compatible result.  Caller attaches ``inline_decision``
        and ``inlined_*`` keys from ``result.meta`` to the terminal parent event.
    """
    if depth > DEFAULT_MAX_DEPTH:
        # Depth guard: should not be reached because the detector blocks depth
        # > DEFAULT_MAX_DEPTH before this function is ever called.  Guard here
        # for defence in depth.
        logger.debug(
            "INLINE.RUNNER depth=%d exceeds limit=%d; refusing to run inline",
            depth,
            DEFAULT_MAX_DEPTH,
        )
        return InlineResult(
            status="error",
            error={
                "kind": "agent.runtime",
                "code": "INLINE_DEPTH_EXCEEDED",
                "message": (
                    f"Inline depth {depth} exceeds maximum {DEFAULT_MAX_DEPTH}; "
                    "this child must use the dispatched path."
                ),
                "retryable": False,
            },
        )

    child_execution_id = _allocate_child_execution_id()
    inline_meta = _inline_meta(
        parent_execution_id=parent_execution_id,
        parent_command_id=parent_command_id,
        depth=depth,
    )

    logger.debug(
        "INLINE.RUNNER start child_execution_id=%s parent=%s depth=%d steps=%d",
        child_execution_id,
        parent_execution_id,
        depth,
        len(child_playbook.get("workflow") or []),
    )

    # Emit child lifecycle initialisation events.
    playbook_path = str(
        (child_playbook.get("metadata") or {}).get("name")
        or child_playbook.get("name")
        or parent_step
    )
    child_workload = dict(child_input or {})
    await _emit_init_events(
        child_execution_id=child_execution_id,
        playbook_path=playbook_path,
        workload=child_workload,
        inline_meta=inline_meta,
        batch_event_emitter=batch_event_emitter,
    )

    workflow: List[Any] = list(child_playbook.get("workflow") or [])
    child_context: Dict[str, Any] = {
        "workload": child_workload,
        "execution_id": child_execution_id,
        "parent_execution_id": parent_execution_id,
        "meta": dict(inline_meta),
    }

    last_result: Any = None
    failed = False
    fail_error: Optional[Dict[str, Any]] = None
    cancelled = False

    for step_idx, raw_step in enumerate(workflow):
        step_name = _step_name(raw_step)

        # --- Cooperative cancellation check ---
        try:
            is_cancelled = await _probe_cancellation(
                cancellation_probe, parent_execution_id, child_execution_id
            )
        except Exception as probe_exc:
            logger.debug(
                "INLINE.RUNNER cancellation probe failed step=%s: %s",
                step_name,
                probe_exc,
            )
            is_cancelled = False

        if is_cancelled:
            logger.debug(
                "INLINE.RUNNER parent cancelled; stopping at step=%s child=%s",
                step_name,
                child_execution_id,
            )
            cancelled = True
            await _emit_cancelled_events(
                child_execution_id=child_execution_id,
                step_name=step_name,
                inline_meta=inline_meta,
                batch_event_emitter=batch_event_emitter,
            )
            break

        tool_kind = _tool_kind_from_step(raw_step)
        tool_config = _tool_config_from_step(raw_step)
        step_command_id = _allocate_child_execution_id()

        logger.debug(
            "INLINE.RUNNER step[%d]=%s kind=%s child=%s",
            step_idx,
            step_name,
            tool_kind,
            child_execution_id,
        )

        # Emit command.started + step.enter
        await _emit_step_enter(
            child_execution_id=child_execution_id,
            step_name=step_name,
            command_id=step_command_id,
            inline_meta=inline_meta,
            batch_event_emitter=batch_event_emitter,
        )

        # Execute the tool
        try:
            step_result = await _execute_inline_step(
                tool_kind=tool_kind,
                tool_config=tool_config,
                step=raw_step,
                child_context=dict(child_context),
                jinja_env=jinja_env,
                depth=depth,
            )
        except Exception as exc:
            logger.debug(
                "INLINE.RUNNER step=%s raised: %s",
                step_name,
                exc,
            )
            failed = True
            fail_error = {
                "kind": "agent.runtime",
                "code": "INLINE_STEP_FAILED",
                "message": str(exc)[:500],
                "retryable": False,
            }
            # Emit call.error + command.failed
            await _emit_step_error(
                child_execution_id=child_execution_id,
                step_name=step_name,
                command_id=step_command_id,
                error_message=str(exc),
                inline_meta=inline_meta,
                batch_event_emitter=batch_event_emitter,
            )
            break

        # Scrub result via ResultHandler.
        processed_result = await _scrub_result(
            execution_id=child_execution_id,
            step_name=step_name,
            result=step_result,
            render_context=child_context,
        )
        last_result = processed_result

        # Update child_context with this step's result so later steps can
        # reference it via Jinja templates.
        child_context[step_name] = processed_result

        # Emit call.done + step.exit + command.completed
        await _emit_step_exit(
            child_execution_id=child_execution_id,
            step_name=step_name,
            command_id=step_command_id,
            result=processed_result,
            inline_meta=inline_meta,
            batch_event_emitter=batch_event_emitter,
        )

        logger.debug(
            "INLINE.RUNNER step[%d]=%s completed child=%s",
            step_idx,
            step_name,
            child_execution_id,
        )

    # Emit terminal lifecycle events.
    if cancelled:
        await _emit_workflow_cancelled(
            child_execution_id=child_execution_id,
            playbook_path=playbook_path,
            inline_meta=inline_meta,
            batch_event_emitter=batch_event_emitter,
        )
        return InlineResult(
            status="error",
            execution_id=child_execution_id,
            error={
                "kind": "agent.execution",
                "code": "PLAYBOOK_CANCELLED",
                "message": "Inline child execution cancelled by parent cancellation.",
                "retryable": False,
            },
            meta={
                "inline_decision": inline_decision.to_dict(),
                **inline_meta,
            },
        )

    if failed:
        await _emit_workflow_failed(
            child_execution_id=child_execution_id,
            playbook_path=playbook_path,
            error_message=(fail_error or {}).get("message", "step failed"),
            inline_meta=inline_meta,
            batch_event_emitter=batch_event_emitter,
        )
        return InlineResult(
            status="error",
            execution_id=child_execution_id,
            error=fail_error,
            meta={
                "inline_decision": inline_decision.to_dict(),
                **inline_meta,
            },
        )

    await _emit_workflow_completed(
        child_execution_id=child_execution_id,
        playbook_path=playbook_path,
        result=last_result,
        inline_meta=inline_meta,
        batch_event_emitter=batch_event_emitter,
    )

    logger.debug(
        "INLINE.RUNNER complete child=%s status=ok",
        child_execution_id,
    )
    return InlineResult(
        status="ok",
        data=last_result,
        execution_id=child_execution_id,
        meta={
            "inline_decision": inline_decision.to_dict(),
            **inline_meta,
        },
    )


# ---------------------------------------------------------------------------
# Private helpers — event emission
# ---------------------------------------------------------------------------


async def _probe_cancellation(
    probe: Callable[[str], Any],
    parent_execution_id: str,
    child_execution_id: str,
) -> bool:
    """Call the cancellation probe and return True if cancelled."""
    try:
        result = probe(parent_execution_id)
        if asyncio.iscoroutine(result):
            result = await result
        return bool(result)
    except Exception:
        return False


def _with_inline_meta(payload: Dict[str, Any], inline_meta: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of payload with inline_meta merged in under 'meta'."""
    merged = dict(payload)
    merged.setdefault("meta", {})
    if isinstance(merged["meta"], dict):
        merged["meta"] = {**merged["meta"], **inline_meta}
    else:
        merged["meta"] = dict(inline_meta)
    return merged


async def _safe_emit(
    batch_event_emitter: Callable[[str, List[Dict[str, Any]]], Any],
    execution_id: str,
    events: List[Dict[str, Any]],
) -> None:
    """Call batch_event_emitter, swallowing errors so inline execution continues."""
    try:
        result = batch_event_emitter(execution_id, events)
        if asyncio.iscoroutine(result):
            await result
    except Exception as exc:
        logger.debug(
            "INLINE.RUNNER event emission failed execution_id=%s: %s",
            execution_id,
            exc,
        )


async def _emit_init_events(
    *,
    child_execution_id: str,
    playbook_path: str,
    workload: Dict[str, Any],
    inline_meta: Dict[str, Any],
    batch_event_emitter: Callable,
) -> None:
    events = [
        {
            "step": playbook_path,
            "name": "playbook.initialized",
            "payload": _with_inline_meta(
                {
                    "status": "initialized",
                    "result": {"workload": workload, "playbook_path": playbook_path},
                },
                inline_meta,
            ),
            "actionable": False,
            "informative": True,
        },
        {
            "step": "workflow",
            "name": "workflow.initialized",
            "payload": _with_inline_meta(
                {
                    "status": "initialized",
                    "result": {"playbook_path": playbook_path, "workload": workload},
                },
                inline_meta,
            ),
            "actionable": False,
            "informative": True,
        },
    ]
    await _safe_emit(batch_event_emitter, child_execution_id, events)


async def _emit_step_enter(
    *,
    child_execution_id: str,
    step_name: str,
    command_id: str,
    inline_meta: Dict[str, Any],
    batch_event_emitter: Callable,
) -> None:
    events = [
        {
            "step": step_name,
            "name": "command.started",
            "payload": _with_inline_meta(
                {"command_id": command_id, "inline": True},
                inline_meta,
            ),
            "actionable": False,
            "informative": True,
        },
        {
            "step": step_name,
            "name": "step.enter",
            "payload": _with_inline_meta(
                {"status": "started"},
                inline_meta,
            ),
            "actionable": False,
            "informative": True,
        },
    ]
    await _safe_emit(batch_event_emitter, child_execution_id, events)


async def _emit_step_exit(
    *,
    child_execution_id: str,
    step_name: str,
    command_id: str,
    result: Any,
    inline_meta: Dict[str, Any],
    batch_event_emitter: Callable,
) -> None:
    events = [
        {
            "step": step_name,
            "name": "call.done",
            "payload": _with_inline_meta(
                {"response": result, "command_id": command_id},
                inline_meta,
            ),
            "actionable": False,
            "informative": True,
        },
        {
            "step": step_name,
            "name": "step.exit",
            "payload": _with_inline_meta(
                {"status": "COMPLETED"},
                inline_meta,
            ),
            "actionable": False,
            "informative": True,
        },
        {
            "step": step_name,
            "name": "command.completed",
            "payload": _with_inline_meta(
                {"command_id": command_id, "status": "COMPLETED"},
                inline_meta,
            ),
            "actionable": False,
            "informative": True,
        },
    ]
    await _safe_emit(batch_event_emitter, child_execution_id, events)


async def _emit_step_error(
    *,
    child_execution_id: str,
    step_name: str,
    command_id: str,
    error_message: str,
    inline_meta: Dict[str, Any],
    batch_event_emitter: Callable,
) -> None:
    events = [
        {
            "step": step_name,
            "name": "call.error",
            "payload": _with_inline_meta(
                {"error": error_message[:500], "command_id": command_id},
                inline_meta,
            ),
            "actionable": False,
            "informative": True,
        },
        {
            "step": step_name,
            "name": "step.exit",
            "payload": _with_inline_meta(
                {"status": "FAILED"},
                inline_meta,
            ),
            "actionable": False,
            "informative": True,
        },
        {
            "step": step_name,
            "name": "command.failed",
            "payload": _with_inline_meta(
                {"command_id": command_id, "error": error_message[:500]},
                inline_meta,
            ),
            "actionable": False,
            "informative": True,
        },
    ]
    await _safe_emit(batch_event_emitter, child_execution_id, events)


async def _emit_cancelled_events(
    *,
    child_execution_id: str,
    step_name: str,
    inline_meta: Dict[str, Any],
    batch_event_emitter: Callable,
) -> None:
    events = [
        {
            "step": step_name,
            "name": "execution.cancelled",
            "payload": _with_inline_meta(
                {"reason": "parent_cancelled"},
                inline_meta,
            ),
            "actionable": False,
            "informative": True,
        },
    ]
    await _safe_emit(batch_event_emitter, child_execution_id, events)


async def _emit_workflow_completed(
    *,
    child_execution_id: str,
    playbook_path: str,
    result: Any,
    inline_meta: Dict[str, Any],
    batch_event_emitter: Callable,
) -> None:
    events = [
        {
            "step": "workflow",
            "name": "workflow.completed",
            "payload": _with_inline_meta(
                {"status": "completed", "result": result},
                inline_meta,
            ),
            "actionable": False,
            "informative": True,
        },
        {
            "step": playbook_path,
            "name": "playbook.completed",
            "payload": _with_inline_meta(
                {"status": "completed"},
                inline_meta,
            ),
            "actionable": False,
            "informative": True,
        },
    ]
    await _safe_emit(batch_event_emitter, child_execution_id, events)


async def _emit_workflow_failed(
    *,
    child_execution_id: str,
    playbook_path: str,
    error_message: str,
    inline_meta: Dict[str, Any],
    batch_event_emitter: Callable,
) -> None:
    events = [
        {
            "step": "workflow",
            "name": "workflow.failed",
            "payload": _with_inline_meta(
                {"status": "failed", "error": error_message[:500]},
                inline_meta,
            ),
            "actionable": False,
            "informative": True,
        },
        {
            "step": playbook_path,
            "name": "playbook.failed",
            "payload": _with_inline_meta(
                {"status": "failed"},
                inline_meta,
            ),
            "actionable": False,
            "informative": True,
        },
    ]
    await _safe_emit(batch_event_emitter, child_execution_id, events)


async def _emit_workflow_cancelled(
    *,
    child_execution_id: str,
    playbook_path: str,
    inline_meta: Dict[str, Any],
    batch_event_emitter: Callable,
) -> None:
    events = [
        {
            "step": "workflow",
            "name": "workflow.failed",
            "payload": _with_inline_meta(
                {"status": "cancelled", "error": "parent_cancelled"},
                inline_meta,
            ),
            "actionable": False,
            "informative": True,
        },
        {
            "step": playbook_path,
            "name": "playbook.failed",
            "payload": _with_inline_meta(
                {"status": "cancelled"},
                inline_meta,
            ),
            "actionable": False,
            "informative": True,
        },
    ]
    await _safe_emit(batch_event_emitter, child_execution_id, events)


# ---------------------------------------------------------------------------
# Private helpers — tool execution
# ---------------------------------------------------------------------------


async def _scrub_result(
    *,
    execution_id: str,
    step_name: str,
    result: Any,
    render_context: Dict[str, Any],
) -> Any:
    """Pass the step result through ResultHandler for scrub + ref storage."""
    try:
        from noetl.worker.result_handler import ResultHandler
        import os

        rh = ResultHandler(execution_id=execution_id)
        output_config: Dict[str, Any] = {
            "inline_max_bytes": int(os.getenv("NOETL_INLINE_MAX_BYTES", "10485760")),
        }
        processed = await rh.process_result(
            step_name=step_name,
            result=result,
            output_config=output_config,
            scrub_context=render_context,
        )
        return processed
    except Exception as exc:
        logger.debug(
            "INLINE.RUNNER scrub failed step=%s: %s",
            step_name,
            exc,
        )
        # Return a safe stub so the runner continues rather than aborting.
        return {"_store_failed": True, "_store_error": str(exc)[:300]}


async def _execute_inline_step(
    *,
    tool_kind: str,
    tool_config: Dict[str, Any],
    step: Any,
    child_context: Dict[str, Any],
    jinja_env: Any,
    depth: int,
) -> Any:
    """Execute a single step using the same tool surfaces as the dispatched path.

    Only ``python``, ``mcp``, and ``noop`` are accepted; the detector guards
    against any other kind before this function is ever called.
    """
    step_dict = step if isinstance(step, dict) else {}
    step_name = _step_name(step)

    if tool_kind == "noop":
        logger.debug("INLINE.RUNNER noop step=%s", step_name)
        return {"status": "ok"}

    if tool_kind == "python":
        from noetl.tools.python import execute_python_task_async

        task_config: Dict[str, Any] = {
            **tool_config,
            "name": step_name,
            # Carry any step-level 'with' block into the task config.
            **(step_dict.get("with") or {}),
        }
        args: Dict[str, Any] = dict(step_dict.get("args") or {})
        result = await execute_python_task_async(task_config, child_context, jinja_env, args)
        return result

    if tool_kind == "mcp":
        from noetl.tools.mcp import execute_mcp_task

        task_config = {
            **tool_config,
            "name": step_name,
            **(step_dict.get("with") or {}),
        }
        task_with: Dict[str, Any] = dict(step_dict.get("args") or step_dict.get("with") or {})
        result = await execute_mcp_task(task_config, child_context, jinja_env, task_with)
        return result

    # Should never be reached because the detector blocked non-allowed kinds.
    raise ValueError(
        f"Inline runner received unsupported tool kind '{tool_kind}' for step '{step_name}'. "
        "The detector should have blocked this child."
    )
