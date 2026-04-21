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
import time
from typing import Any, Awaitable, Callable, Optional

from jinja2 import Environment

from noetl.core.cursor_drivers import CursorDriverNotFoundError, get_driver
from noetl.core.logger import setup_logger
from noetl.worker.secrets import fetch_credential_by_key_async
from noetl.worker.task_sequence_executor import TaskSequenceExecutor

logger = setup_logger(__name__, include_location=True)


# Safety cap so a misconfigured claim (e.g. a claim that never marks
# rows as claimed) can't spin forever.  Playbook authors can raise it
# via cursor.options.max_iterations; the default is generous for the
# PFT-style 10 000-row per-facility workloads.
_DEFAULT_MAX_ITERATIONS = 100_000


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

    # Render the claim SQL once at open-time.  execution_id /
    # facility / etc. are stable for the lifetime of this worker; the
    # only per-claim substitution lives in the claim SQL itself
    # (e.g. a `FOR UPDATE SKIP LOCKED` clause plus worker_slot_id
    # parameters).  Per-row values from `iter.<iterator>` are only
    # valid inside the task pipeline, not the claim.
    claim_context = dict(context or {})
    if worker_slot_id and "__worker_slot_id" not in claim_context:
        claim_context["__worker_slot_id"] = worker_slot_id
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
    started_at = time.monotonic()
    try:
        while processed + failed < max_iterations:
            claim_ctx = {
                "execution_id": context.get("execution_id"),
                "worker_slot_id": worker_slot_id,
                "iteration": processed,
            }
            row = await driver.claim(handle, claim_ctx)
            if row is None:
                logger.info(
                    "[CURSOR-WORKER] slot=%s drained after %d processed / %d failed",
                    worker_slot_id, processed, failed,
                )
                break

            # Per-claim base context: clone the command context so
            # per-row iter values never leak into the next claim.
            per_claim_ctx = dict(context or {})
            iter_namespace = dict(per_claim_ctx.get("iter") or {})
            iter_namespace[iterator_name] = row
            iter_namespace["_index"] = processed
            iter_namespace["_worker_slot_id"] = worker_slot_id
            per_claim_ctx["iter"] = iter_namespace

            try:
                result = await seq_executor.execute(
                    tasks=tasks,
                    base_context=per_claim_ctx,
                )
            except Exception as exc:
                failed += 1
                logger.exception(
                    "[CURSOR-WORKER] slot=%s iteration=%s: task sequence raised %s",
                    worker_slot_id, processed, exc,
                )
                # Driver's claim is responsible for marking the row in
                # a state that allows reclaim (e.g. leaving status in
                # 'claimed' until a timeout prelude resets it).
                continue

            if isinstance(result, dict):
                status = str(result.get("status", "")).lower()
                if status == "failed":
                    failed += 1
                elif status == "break":
                    breaks += 1
                    logger.info(
                        "[CURSOR-WORKER] slot=%s: task sequence returned break; "
                        "stopping this worker early",
                        worker_slot_id,
                    )
                    processed += 1
                    break
            processed += 1

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
        "worker_slot_id": worker_slot_id,
        "duration_s": round(duration_s, 3),
    }


__all__ = ["execute_cursor_worker"]
