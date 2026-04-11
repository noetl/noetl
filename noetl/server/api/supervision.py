from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from noetl.core.cache import get_nats_cache
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)

_COMMAND_TERMINAL_STATUS = {
    "call.done": "COMPLETED",
    "call.error": "FAILED",
    "command.completed": "COMPLETED",
    "command.failed": "FAILED",
    "command.cancelled": "CANCELLED",
}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_result_pointer(payload: Any) -> Optional[dict[str, Any]]:
    """Extract a compact ref/pointer from a reference-only event payload."""
    if not isinstance(payload, dict):
        return None

    candidates: list[Any] = [
        payload.get("response"),
        payload.get("result"),
        payload.get("reference"),
        payload,
    ]

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue

        direct_ref = candidate.get("_ref")
        if isinstance(direct_ref, dict) and direct_ref.get("ref"):
            pointer = dict(direct_ref)
            if "kind" not in pointer:
                pointer["kind"] = "result_ref"
            return pointer

        if candidate.get("kind") in {"result_ref", "temp_ref"} and candidate.get("ref"):
            return {
                "kind": candidate.get("kind"),
                "ref": candidate.get("ref"),
                "store": candidate.get("store"),
            }

        reference = candidate.get("reference")
        if isinstance(reference, dict):
            locator = reference.get("locator") or reference.get("ref")
            if locator:
                return {
                    "kind": "result_ref",
                    "ref": locator,
                    "store": reference.get("store"),
                }

    return None


async def supervise_command_issued(
    execution_id: str,
    command_id: str,
    step_name: str,
    *,
    event_id: Optional[int] = None,
    meta: Optional[dict[str, Any]] = None,
) -> None:
    """Persist issued-command metadata into the lightweight supervisor."""
    if not command_id:
        return

    try:
        cache = await get_nats_cache()
        await cache.register_command_issued(
            str(execution_id),
            str(command_id),
            str(step_name),
            command_event_id=event_id,
            meta=meta,
        )

        loop_step = None
        loop_event_id = None
        loop_iteration_index = None
        if isinstance(meta, dict):
            loop_step = meta.get("loop_step")
            loop_event_id = meta.get("loop_event_id") or meta.get("__loop_epoch_id")
            loop_iteration_index = meta.get("loop_iteration_index")

        if loop_event_id and loop_iteration_index is not None:
            normalized_loop_step = str(loop_step or step_name.replace(":task_sequence", ""))
            await cache.set_loop_iteration_state(
                str(execution_id),
                normalized_loop_step,
                int(loop_iteration_index),
                {
                    "status": "ISSUED",
                    "command_id": str(command_id),
                    "command_step": str(step_name),
                    "command_event_id": event_id,
                    "last_event_name": "command.issued",
                    "last_event_id": event_id,
                    "issued_at": _utcnow_iso(),
                },
                event_id=str(loop_event_id),
            )
    except Exception as exc:
        logger.warning(
            "[SUPERVISOR] Failed to register issued command state for execution=%s command_id=%s: %s",
            execution_id,
            command_id,
            exc,
        )


async def supervise_persisted_event(
    execution_id: str,
    step_name: str,
    event_name: str,
    payload: dict[str, Any],
    meta: Optional[dict[str, Any]],
    *,
    event_id: Optional[int] = None,
) -> None:
    """Update supervisor state after a workflow-driving event is persisted."""
    normalized_name = str(event_name or "")
    command_status = _COMMAND_TERMINAL_STATUS.get(normalized_name)

    try:
        cache = await get_nats_cache()
    except Exception as exc:
        logger.warning(
            "[SUPERVISOR] Failed to access cache for execution=%s step=%s event=%s: %s",
            execution_id,
            step_name,
            event_name,
            exc,
        )
        return

    command_id = None
    if isinstance(meta, dict):
        command_id = meta.get("command_id")
    if not command_id and isinstance(payload, dict):
        command_id = payload.get("command_id")

    if command_status and command_id:
        try:
            await cache.mark_command_terminal(
                str(execution_id),
                str(command_id),
                command_status,
                event_name=normalized_name,
                event_id=event_id,
                step_name=str(step_name),
            )
        except Exception as exc:
            logger.warning(
                "[SUPERVISOR] Failed to mark command terminal for execution=%s command_id=%s: %s",
                execution_id,
                command_id,
                exc,
            )

    loop_event_id = None
    loop_iteration_index = None
    if isinstance(meta, dict):
        loop_event_id = meta.get("loop_event_id") or meta.get("__loop_epoch_id")
        loop_iteration_index = meta.get("loop_iteration_index")
    if isinstance(payload, dict):
        if loop_event_id is None:
            loop_event_id = payload.get("loop_event_id")
        if loop_iteration_index is None:
            loop_iteration_index = payload.get("loop_iteration_index")

    if loop_event_id is None or loop_iteration_index is None:
        return

    normalized_step = str(step_name).replace(":task_sequence", "")
    try:
        lifecycle_update: dict[str, Any] = {
            "last_event_name": normalized_name,
            "last_event_id": event_id,
        }
        if command_id:
            lifecycle_update["command_id"] = str(command_id)
        if normalized_name == "command.claimed":
            lifecycle_update["claimed_at"] = _utcnow_iso()
        elif normalized_name == "command.started":
            lifecycle_update["status"] = "STARTED"
            lifecycle_update["started_at"] = _utcnow_iso()

        if normalized_name in {"command.claimed", "command.started"}:
            await cache.set_loop_iteration_state(
                str(execution_id),
                normalized_step,
                int(loop_iteration_index),
                lifecycle_update,
                event_id=str(loop_event_id),
            )
            return

        if normalized_name not in {"call.done", "call.error"}:
            return

        result_pointer = _extract_result_pointer(payload)

        # Keep the result pointer addressable for resume/recovery, but let the
        # engine own the terminal transition so it can advance loop progress
        # exactly once per (epoch, iteration).
        update_payload = dict(lifecycle_update)
        if result_pointer:
            update_payload["result_pointer"] = result_pointer

        await cache.set_loop_iteration_state(
            str(execution_id),
            normalized_step,
            int(loop_iteration_index),
            update_payload,
            event_id=str(loop_event_id),
        )
    except Exception as exc:
        logger.warning(
            "[SUPERVISOR] Failed to persist loop iteration state for execution=%s step=%s index=%s: %s",
            execution_id,
            normalized_step,
            loop_iteration_index,
            exc,
        )
