"""Cursor-driven loop worker runtime.

A cursor worker command carries a cursor spec + iterator name + task
pipeline.  The worker opens a driver handle (see
:mod:`noetl.core.cursor_drivers`), then loops over ``claim → render
iter.<iterator> → run task sequence → repeat`` until the driver
returns no row.  One terminal ``call.done`` is emitted per worker when
the cursor drains.

This path bypasses the engine's claim_next_loop_index / CAS machinery
entirely — atomicity lives in the driver's claim statement.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Awaitable, Callable, Optional

import httpx
from jinja2 import Environment

from noetl.core.cursor_drivers import CursorDriverNotFoundError, get_driver
from noetl.core.logger import setup_logger
from noetl.core.storage import (
    ARROW_STREAM_MEDIA_TYPE,
    ArrowIpcSharedMemoryCache,
    Scope,
    StoreTier,
    default_store,
    rows_to_arrow_ipc,
)
from noetl.worker.secrets import fetch_credential_by_key_async
from noetl.worker.task_sequence_executor import TaskSequenceExecutor

logger = setup_logger(__name__, include_location=True)


# Safety cap so a misconfigured claim (e.g. a claim that never marks
# rows as claimed) can't spin forever.  Playbook authors can raise it
# via cursor.options.max_iterations; the default is generous for the
# PFT-style 10 000-row per-facility workloads.
_DEFAULT_MAX_ITERATIONS = 100_000

_FRAME_IPC_CACHE: Optional[ArrowIpcSharedMemoryCache] = None


def _truthy_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _frame_ipc_cache() -> Optional[ArrowIpcSharedMemoryCache]:
    if not _truthy_env("NOETL_CURSOR_FRAME_IPC_ENABLED", default=True):
        return None
    global _FRAME_IPC_CACHE
    if _FRAME_IPC_CACHE is None:
        _FRAME_IPC_CACHE = ArrowIpcSharedMemoryCache(
            namespace=os.getenv("NOETL_CURSOR_FRAME_IPC_NAMESPACE", "noetl_frame"),
            producer=os.getenv("HOSTNAME") or "cursor-worker",
        )
    return _FRAME_IPC_CACHE


def _estimate_row_bytes(row: dict[str, Any]) -> int:
    try:
        return len(json.dumps(row, default=str).encode("utf-8"))
    except Exception:
        return 1024


async def _store_claimed_frame(
    *,
    execution_id: Any,
    worker_slot_id: Optional[str],
    frame_index: int,
    rows: list[dict[str, Any]],
    frame_policy: dict[str, Any],
) -> Optional[dict[str, Any]]:
    if not rows:
        return None

    force_capture = _truthy_env("NOETL_CURSOR_FRAME_CAPTURE_ENABLED", default=False)
    if not force_capture and int(frame_policy.get("max_rows") or 1) <= 1:
        return None

    try:
        payload, schema_digest, row_count = await asyncio.to_thread(rows_to_arrow_ipc, rows)
        ref = await default_store.put_ipc_bytes(
            execution_id=str(execution_id or "unknown"),
            name=f"cursor-frame-{worker_slot_id or 'slot'}-{frame_index}",
            data_bytes=payload,
            schema_digest=schema_digest,
            row_count=row_count,
            scope=Scope.EXECUTION,
            store=StoreTier.KV,
            source_step=str(worker_slot_id or "cursor_worker"),
            ipc_cache=_frame_ipc_cache(),
            ipc_lease_seconds=frame_policy.get("lease_seconds"),
            media_type=ARROW_STREAM_MEDIA_TYPE,
        )
        return {
            "frame_index": frame_index,
            "row_count": row_count,
            "rows_ref": ref.model_dump(mode="json"),
            "schema_digest": schema_digest,
            "media_type": ARROW_STREAM_MEDIA_TYPE,
        }
    except Exception as exc:
        logger.debug(
            "[CURSOR-WORKER] slot=%s frame=%s row capture skipped: %s",
            worker_slot_id,
            frame_index,
            exc,
        )
        return {
            "frame_index": frame_index,
            "row_count": len(rows),
            "capture_failed": True,
            "capture_error": str(exc)[:300],
        }


def _runtime_api_base(context: dict[str, Any]) -> str:
    return str(
        context.get("server_url")
        or os.getenv("NOETL_SERVER_URL")
        or os.getenv("NOETL_API_URL")
        or "http://noetl.noetl.svc.cluster.local:8082"
    ).rstrip("/")


async def _claim_runtime_frame(
    *,
    context: dict[str, Any],
    stage_id: Any,
    worker_slot_id: Optional[str],
    frame_index: int,
    frame_policy: dict[str, Any],
    cursor: dict[str, Any],
) -> Optional[dict[str, Any]]:
    if not stage_id:
        return None
    command_id = None
    if isinstance(context, dict):
        command_id = context.get("command_id")
        event_context = context.get("event")
        if command_id is None and isinstance(event_context, dict):
            command_id = event_context.get("command_id")
    try:
        lease_seconds = int(float(frame_policy.get("lease_seconds") or 120.0))
        payload = {
            "worker_id": worker_slot_id or os.getenv("HOSTNAME") or "cursor-worker",
            "command_id": command_id,
            "requested_count": 1,
            "lease_seconds": lease_seconds,
            "frame_policy": frame_policy or {},
            "cursor": {
                **(cursor or {}),
                "frame_index": frame_index,
                "worker_slot_id": worker_slot_id,
            },
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{_runtime_api_base(context)}/api/stages/{stage_id}/frames/claim",
                json=payload,
            )
            response.raise_for_status()
            frames = (response.json() or {}).get("frames") or []
            return dict(frames[0]) if frames else None
    except Exception as exc:
        logger.warning(
            "[CURSOR-WORKER] slot=%s frame=%s stage=%s claim failed; continuing legacy path: %s",
            worker_slot_id,
            frame_index,
            stage_id,
            exc,
        )
        return None


async def _start_runtime_frame(
    *,
    context: dict[str, Any],
    runtime_frame: Optional[dict[str, Any]],
    worker_slot_id: Optional[str],
    lease_seconds: int,
) -> None:
    if not runtime_frame:
        return
    frame_id = runtime_frame.get("frame_id")
    if not frame_id:
        return
    try:
        payload = {
            "worker_id": worker_slot_id or os.getenv("HOSTNAME") or "cursor-worker",
            "status": "RUNNING",
            "lease_seconds": lease_seconds,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{_runtime_api_base(context)}/api/frames/{frame_id}/heartbeat",
                json=payload,
            )
            response.raise_for_status()
    except Exception as exc:
        logger.warning(
            "[CURSOR-WORKER] slot=%s frame_id=%s start heartbeat failed; continuing: %s",
            worker_slot_id,
            frame_id,
            exc,
        )


async def _commit_runtime_frame(
    *,
    context: dict[str, Any],
    runtime_frame: Optional[dict[str, Any]],
    worker_slot_id: Optional[str],
    row_count: int,
    output_ref: Optional[dict[str, Any]],
    events_emitted: int,
    failed: bool,
    metrics: Optional[dict[str, Any]] = None,
    error: Optional[str] = None,
) -> None:
    if not runtime_frame:
        return
    frame_id = runtime_frame.get("frame_id")
    if not frame_id:
        return
    try:
        cursor_payload = dict(runtime_frame.get("cursor") or {})
        if metrics:
            cursor_payload["metrics"] = metrics
        payload = {
            "worker_id": worker_slot_id or os.getenv("HOSTNAME") or "cursor-worker",
            "status": "FAILED" if failed else "COMPLETED",
            "row_count": row_count,
            "output_ref": output_ref,
            "events_emitted": events_emitted,
            "cursor": cursor_payload,
            "error": error,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{_runtime_api_base(context)}/api/frames/{frame_id}/commit",
                json=payload,
            )
            response.raise_for_status()
    except Exception as exc:
        logger.warning(
            "[CURSOR-WORKER] slot=%s frame_id=%s commit failed; frame table may lag: %s",
            worker_slot_id,
            frame_id,
            exc,
        )


async def _claim_frame_rows(
    *,
    driver: Any,
    handle: Any,
    base_context: dict[str, Any],
    worker_slot_id: Optional[str],
    frame_index: int,
    max_rows: int,
    max_iterations_remaining: int,
) -> list[dict[str, Any]]:
    """Claim a frame worth of rows using a batched driver path when present."""

    if max_iterations_remaining <= 0:
        return []

    target_rows = max(1, min(int(max_rows or 1), int(max_iterations_remaining)))
    claim_ctx = {
        "execution_id": base_context.get("execution_id"),
        "worker_slot_id": worker_slot_id,
        "iteration": 0,
        "frame_index": frame_index,
        "frame_row_index": 0,
        "max_rows": target_rows,
    }
    claim_many = getattr(driver, "claim_many", None)
    if callable(claim_many):
        claimed = await claim_many(handle, claim_ctx, target_rows)
        return [dict(row) for row in (claimed or [])[:target_rows]]

    rows: list[dict[str, Any]] = []
    for frame_row_index in range(target_rows):
        claim_ctx = {
            "execution_id": base_context.get("execution_id"),
            "worker_slot_id": worker_slot_id,
            "iteration": frame_row_index,
            "frame_index": frame_index,
            "frame_row_index": frame_row_index,
            "max_rows": target_rows,
        }
        row = await driver.claim(handle, claim_ctx)
        if row is None:
            break
        rows.append(dict(row))
    return rows


def _empty_frame_metrics(*, row_count: int, row_concurrency: int) -> dict[str, Any]:
    return {
        "row_count": row_count,
        "row_concurrency": row_concurrency,
        "process": "row",
        "rows": {
            "ok": 0,
            "failed": 0,
            "break": 0,
        },
        "tasks": {
            "count": 0,
            "duration_ms": 0,
            "render_ms": 0,
            "tool_ms": 0,
            "by_kind": {},
            "by_name": {},
        },
    }


def _merge_metric_bucket(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in (source or {}).items():
        slot = target.setdefault(
            str(key),
            {
                "count": 0,
                "error_count": 0,
                "duration_ms": 0,
                "render_ms": 0,
                "tool_ms": 0,
            },
        )
        for metric_key in ("count", "error_count", "duration_ms", "render_ms", "tool_ms"):
            slot[metric_key] = int(slot.get(metric_key) or 0) + int(value.get(metric_key) or 0)


def _aggregate_frame_metrics(row_results: list[dict[str, Any]], *, row_count: int, row_concurrency: int) -> dict[str, Any]:
    metrics = _empty_frame_metrics(row_count=row_count, row_concurrency=row_concurrency)
    for row_result in row_results:
        status = str(row_result.get("status") or "unknown")
        if status in metrics["rows"]:
            metrics["rows"][status] += 1
        sequence_metrics = row_result.get("metrics") if isinstance(row_result, dict) else None
        if not isinstance(sequence_metrics, dict):
            continue
        tasks = metrics["tasks"]
        tasks["count"] += int(sequence_metrics.get("task_count") or 0)
        tasks["duration_ms"] += int(sequence_metrics.get("duration_ms") or 0)
        tasks["render_ms"] += int(sequence_metrics.get("render_ms") or 0)
        tasks["tool_ms"] += int(sequence_metrics.get("tool_ms") or 0)
        _merge_metric_bucket(tasks["by_kind"], sequence_metrics.get("by_kind") or {})
        _merge_metric_bucket(tasks["by_name"], sequence_metrics.get("by_name") or {})
    return metrics


def _frame_sequence_status(result: Any) -> str:
    if isinstance(result, dict):
        status = str(result.get("status", "")).lower()
        if status == "failed":
            return "failed"
        if status == "break":
            return "break"
    return "ok"


async def execute_cursor_worker(
    *,
    config: dict[str, Any],
    context: dict[str, Any],
    jinja_env: Environment,
    tool_executor: Callable[[str, dict, dict], Awaitable[Any]],
    render_template: Callable[[str, dict], Any],
    render_dict: Callable[[dict, dict], dict],
    worker_slot_id: Optional[str] = None,
) -> dict[str, Any]:
    """Run the claim-process-release loop for one cursor worker slot.

    ``config`` is the command's ``tool.config`` payload:

    .. code-block:: python

        {
            "cursor": {"kind": "postgres", "auth": "pg_k8s",
                       "claim": "UPDATE ... RETURNING ...",
                       "options": {...}},
            "iterator": "patient",
            "tasks": [ ... labeled task list ... ],
        }

    ``context`` is the engine-built render context (execution_id,
    workload, ctx, etc.) — the same base context a normal task_sequence
    command receives.  The worker injects ``iter.<iterator> = row`` per
    claim before delegating to :class:`TaskSequenceExecutor`.
    """
    cursor_spec = config.get("cursor") or {}
    iterator_name = config.get("iterator") or cursor_spec.get("iterator") or "item"
    tasks = config.get("tasks") or []

    if not cursor_spec:
        raise ValueError("cursor_worker: missing cursor spec in tool.config")
    if not tasks:
        raise ValueError("cursor_worker: empty task pipeline in tool.config")

    kind = cursor_spec.get("kind")
    auth_key = cursor_spec.get("auth")
    claim_template = cursor_spec.get("claim")
    options = dict(cursor_spec.get("options") or {})
    if not kind or not auth_key or not claim_template:
        raise ValueError(
            "cursor_worker: cursor spec requires kind/auth/claim "
            f"(got kind={kind!r}, auth={auth_key!r}, "
            f"claim_present={bool(claim_template)})"
        )

    frame_policy = dict(config.get("frame_policy") or {})
    max_frame_rows = max(1, int(frame_policy.get("max_rows") or 1))
    max_frame_seconds = max(0.001, float(frame_policy.get("max_seconds") or 30.0))
    max_frame_bytes = max(1, int(frame_policy.get("max_bytes") or 64 * 1024 * 1024))
    row_concurrency = max(1, int(frame_policy.get("row_concurrency") or 1))
    frame_process = str(frame_policy.get("process") or "row").strip().lower()
    if frame_process not in {"row", "frame"}:
        raise ValueError(f"cursor_worker: unsupported frame.process={frame_process!r}")

    # Render the claim SQL once at open-time.  execution_id /
    # facility / etc. are stable for the lifetime of this worker; the
    # only per-claim substitution lives in the claim SQL itself
    # (e.g. a `FOR UPDATE SKIP LOCKED` clause plus worker_slot_id
    # parameters).  Per-row values from `iter.<iterator>` are only
    # valid inside the task pipeline, not the claim.
    claim_context = dict(context or {})
    if worker_slot_id and "__worker_slot_id" not in claim_context:
        claim_context["__worker_slot_id"] = worker_slot_id
    claim_context["__frame_max_rows"] = max_frame_rows
    claim_context["__frame_policy"] = frame_policy
    rendered_claim_sql = render_template(claim_template, claim_context)
    if not isinstance(rendered_claim_sql, str) or not rendered_claim_sql.strip():
        raise ValueError(
            "cursor_worker: claim SQL rendered to empty/non-string value"
        )
    _ctx_sample = claim_context.get("ctx") if isinstance(claim_context, dict) else None
    _lnf = claim_context.get("load_next_facility") if isinstance(claim_context, dict) else None
    _lnf_ctx = _lnf.get("context") if isinstance(_lnf, dict) else None
    _lnf_ctx_rows = _lnf_ctx.get("rows") if isinstance(_lnf_ctx, dict) else None
    _first_row = _lnf_ctx_rows[0] if isinstance(_lnf_ctx_rows, list) and _lnf_ctx_rows else None
    logger.info(
        "[CURSOR-WORKER] slot=%s opening driver; "
        "lnf_keys=%s lnf_ctx_keys=%s lnf_ctx_rows_len=%s first_row=%s "
        "claim_sql_head=%s",
        worker_slot_id,
        list(_lnf.keys()) if isinstance(_lnf, dict) else None,
        list(_lnf_ctx.keys()) if isinstance(_lnf_ctx, dict) else None,
        len(_lnf_ctx_rows) if isinstance(_lnf_ctx_rows, list) else None,
        _first_row,
        rendered_claim_sql[:400].replace("\n", " "),
    )

    # Resolve the credential via the same endpoint tools use today.
    credential = await fetch_credential_by_key_async(auth_key)
    if not credential:
        raise ValueError(
            f"cursor_worker: credential {auth_key!r} not found or empty"
        )

    try:
        driver = get_driver(kind)
    except CursorDriverNotFoundError:
        raise

    driver_spec = {
        "kind": kind,
        "claim": rendered_claim_sql,
        "options": options,
    }
    stage_id = config.get("stage_id")

    # TaskSequenceExecutor is re-used across claims — it has no
    # per-invocation state that bleeds between rows because `execute`
    # builds a fresh TaskSequenceContext each call.
    seq_executor = TaskSequenceExecutor(
        tool_executor=tool_executor,
        render_template=render_template,
        render_dict=render_dict,
    )

    max_iterations = int(options.get("max_iterations") or _DEFAULT_MAX_ITERATIONS)
    handle = await driver.open(credential, driver_spec)

    processed = 0
    failed = 0
    breaks = 0
    frame_count = 0
    frames: list[dict[str, Any]] = []
    started_at = time.monotonic()
    try:
        while processed + failed < max_iterations:
            frame_started_at = time.monotonic()
            frame_rows = await _claim_frame_rows(
                driver=driver,
                handle=handle,
                base_context=context,
                worker_slot_id=worker_slot_id,
                frame_index=frame_count,
                max_rows=max_frame_rows,
                max_iterations_remaining=max_iterations - (processed + failed),
            )
            frame_bytes = sum(_estimate_row_bytes(row_dict) for row_dict in frame_rows)
            if frame_bytes >= max_frame_bytes:
                logger.debug(
                    "[CURSOR-WORKER] slot=%s frame=%s claimed %d bytes, above frame max_bytes=%d",
                    worker_slot_id,
                    frame_count,
                    frame_bytes,
                    max_frame_bytes,
                )
            if time.monotonic() - frame_started_at >= max_frame_seconds:
                logger.debug(
                    "[CURSOR-WORKER] slot=%s frame=%s claim took longer than max_seconds=%s",
                    worker_slot_id,
                    frame_count,
                    max_frame_seconds,
                )

            if not frame_rows:
                logger.info(
                    "[CURSOR-WORKER] slot=%s drained after %d processed / %d failed",
                    worker_slot_id, processed, failed,
                )
                break

            runtime_frame = await _claim_runtime_frame(
                context=context,
                stage_id=stage_id,
                worker_slot_id=worker_slot_id,
                frame_index=frame_count,
                frame_policy=frame_policy,
                cursor={
                    "kind": kind,
                    "iterator": iterator_name,
                    "row_count": len(frame_rows),
                },
            )
            await _start_runtime_frame(
                context=context,
                runtime_frame=runtime_frame,
                worker_slot_id=worker_slot_id,
                lease_seconds=int(float(frame_policy.get("lease_seconds") or 120.0)),
            )
            frame_meta = await _store_claimed_frame(
                execution_id=context.get("execution_id"),
                worker_slot_id=worker_slot_id,
                frame_index=frame_count,
                rows=frame_rows,
                frame_policy=frame_policy,
            )
            if frame_meta is not None:
                frames.append(frame_meta)

            stop_after_frame = False
            frame_failed_before = failed
            frame_base_index = processed + failed

            async def _execute_whole_frame() -> dict[str, Any]:
                per_frame_ctx = dict(context or {})
                iter_namespace = dict(per_frame_ctx.get("iter") or {})
                iter_namespace[f"{iterator_name}_rows"] = frame_rows
                iter_namespace[iterator_name] = frame_rows
                iter_namespace["_index"] = frame_base_index
                iter_namespace["_worker_slot_id"] = worker_slot_id
                iter_namespace["_frame_index"] = frame_count
                iter_namespace["_frame_row_count"] = len(frame_rows)
                per_frame_ctx["iter"] = iter_namespace
                per_frame_ctx["frame"] = {
                    "index": frame_count,
                    "base_index": frame_base_index,
                    "row_count": len(frame_rows),
                    "rows": frame_rows,
                    "worker_slot_id": worker_slot_id,
                    "policy": frame_policy,
                }

                try:
                    result = await seq_executor.execute(
                        tasks=tasks,
                        base_context=per_frame_ctx,
                    )
                except Exception as exc:
                    logger.exception(
                        "[CURSOR-WORKER] slot=%s frame=%s: frame task sequence raised %s",
                        worker_slot_id,
                        frame_count,
                        exc,
                    )
                    return {"status": "failed"}

                if isinstance(result, dict):
                    return {
                        "status": _frame_sequence_status(result),
                        "metrics": result.get("metrics"),
                    }
                return {"status": "ok"}

            async def _execute_frame_row(frame_row_index: int, row: dict[str, Any]) -> dict[str, Any]:
                per_claim_ctx = dict(context or {})
                iter_namespace = dict(per_claim_ctx.get("iter") or {})
                iter_namespace[iterator_name] = row
                iter_namespace["_index"] = frame_base_index + frame_row_index
                iter_namespace["_worker_slot_id"] = worker_slot_id
                iter_namespace["_frame_index"] = frame_count
                iter_namespace["_frame_row_index"] = frame_row_index
                per_claim_ctx["iter"] = iter_namespace

                try:
                    result = await seq_executor.execute(
                        tasks=tasks,
                        base_context=per_claim_ctx,
                    )
                except Exception as exc:
                    logger.exception(
                        "[CURSOR-WORKER] slot=%s iteration=%s: task sequence raised %s",
                        worker_slot_id,
                        frame_base_index + frame_row_index,
                        exc,
                    )
                    # Driver's claim is responsible for marking the row in
                    # a state that allows reclaim (e.g. leaving status in
                    # 'claimed' until a timeout prelude resets it).
                    return {"status": "failed"}

                if isinstance(result, dict):
                    status = str(result.get("status", "")).lower()
                    if status == "failed":
                        return {"status": "failed", "metrics": result.get("metrics")}
                    if status == "break":
                        return {"status": "break", "metrics": result.get("metrics")}
                    return {"status": "ok", "metrics": result.get("metrics")}
                return {"status": "ok"}

            if frame_process == "frame":
                frame_status = await _execute_whole_frame()
                row_status = frame_status.get("status")
                frame_metrics = _aggregate_frame_metrics(
                    [frame_status],
                    row_count=len(frame_rows),
                    row_concurrency=1,
                )
                frame_metrics["process"] = "frame"
                frame_metrics["rows"]["ok"] = len(frame_rows) if row_status == "ok" else 0
                frame_metrics["rows"]["failed"] = len(frame_rows) if row_status == "failed" else 0
                frame_metrics["rows"]["break"] = len(frame_rows) if row_status == "break" else 0
            elif row_concurrency <= 1 or len(frame_rows) <= 1:
                row_statuses = []
                for frame_row_index, row in enumerate(frame_rows):
                    row_status = await _execute_frame_row(frame_row_index, row)
                    row_statuses.append(row_status)
                    if row_status.get("status") == "break":
                        logger.info(
                            "[CURSOR-WORKER] slot=%s: task sequence returned break; "
                            "stopping this worker early",
                            worker_slot_id,
                        )
                        break
                frame_metrics = _aggregate_frame_metrics(
                    row_statuses,
                    row_count=len(frame_rows),
                    row_concurrency=row_concurrency,
                )
            else:
                semaphore = asyncio.Semaphore(row_concurrency)

                async def _bounded_execute(frame_row_index: int, row: dict[str, Any]) -> str:
                    async with semaphore:
                        return await _execute_frame_row(frame_row_index, row)

                row_statuses = await asyncio.gather(
                    *[_bounded_execute(frame_row_index, row) for frame_row_index, row in enumerate(frame_rows)]
                )
                if any(item.get("status") == "break" for item in row_statuses):
                    logger.info(
                        "[CURSOR-WORKER] slot=%s: task sequence returned break inside concurrent frame; "
                        "stopping this worker after committed frame",
                        worker_slot_id,
                    )
                frame_metrics = _aggregate_frame_metrics(
                    row_statuses,
                    row_count=len(frame_rows),
                    row_concurrency=row_concurrency,
                )
            failed += int(frame_metrics["rows"].get("failed") or 0)
            breaks += int(frame_metrics["rows"].get("break") or 0)
            processed += int(frame_metrics["rows"].get("ok") or 0) + int(frame_metrics["rows"].get("break") or 0)
            stop_after_frame = int(frame_metrics["rows"].get("break") or 0) > 0

            frame_failed = failed > frame_failed_before
            if frame_meta is not None:
                frame_meta["metrics"] = frame_metrics
            await _commit_runtime_frame(
                context=context,
                runtime_frame=runtime_frame,
                worker_slot_id=worker_slot_id,
                row_count=len(frame_rows),
                output_ref=frame_meta,
                events_emitted=len(frame_rows),
                failed=frame_failed,
                metrics=frame_metrics,
                error="one or more frame rows failed" if frame_failed else None,
            )
            frame_count += 1
            if stop_after_frame:
                break

            # Yield to the event loop so heartbeats & shutdown signals
            # have a chance to fire between claims.
            if processed % 25 == 0:
                await asyncio.sleep(0)
        else:
            logger.warning(
                "[CURSOR-WORKER] slot=%s hit max_iterations=%d safety cap "
                "(processed=%d failed=%d) — check claim SQL / reclaim hook",
                worker_slot_id, max_iterations, processed, failed,
            )
    finally:
        try:
            await driver.close(handle)
        except Exception:
            logger.exception("[CURSOR-WORKER] driver.close failed for slot=%s", worker_slot_id)

    duration_s = time.monotonic() - started_at
    outcome_status = "ok" if failed == 0 else "partial"
    return {
        "status": outcome_status,
        "processed": processed,
        "failed": failed,
        "breaks": breaks,
        "frame_count": frame_count,
        "frames": frames,
        "worker_slot_id": worker_slot_id,
        "duration_s": round(duration_s, 3),
    }


__all__ = ["execute_cursor_worker"]
