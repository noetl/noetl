"""
Readiness-gated recovery for interrupted parent playbook executions.

On server startup, recovery is delayed until core dependencies are healthy:
- PostgreSQL reachable
- NATS reachable
- worker pool heartbeat present
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from psycopg.rows import dict_row
from psycopg.types.json import Json

from noetl.core.db.pool import get_pool_connection, get_snowflake_id
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)

_AUTO_RESUME_ENABLED = os.getenv("NOETL_AUTO_RESUME_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_AUTO_RESUME_MODE = os.getenv("NOETL_AUTO_RESUME_MODE", "restart").strip().lower()
_AUTO_RESUME_LOOKBACK_MINUTES = max(
    1,
    int(os.getenv("NOETL_AUTO_RESUME_LOOKBACK_MINUTES", "15")),
)
_AUTO_RESUME_MAX_CANDIDATES = max(
    1,
    int(os.getenv("NOETL_AUTO_RESUME_MAX_CANDIDATES", "1")),
)
_AUTO_RESUME_READINESS_TIMEOUT_SECONDS = max(
    1.0,
    float(os.getenv("NOETL_AUTO_RESUME_READINESS_TIMEOUT_SECONDS", "300")),
)
_AUTO_RESUME_READINESS_POLL_SECONDS = max(
    0.5,
    float(os.getenv("NOETL_AUTO_RESUME_READINESS_POLL_SECONDS", "5")),
)
_AUTO_RESUME_STARTUP_DELAY_SECONDS = max(
    0.0,
    float(os.getenv("NOETL_AUTO_RESUME_STARTUP_DELAY_SECONDS", "3")),
)
_AUTO_RESUME_WORKER_HEARTBEAT_MAX_AGE_SECONDS = max(
    5.0,
    float(os.getenv("NOETL_AUTO_RESUME_WORKER_HEARTBEAT_MAX_AGE_SECONDS", "60")),
)
_AUTO_RESUME_MIN_READY_WORKERS = max(
    1,
    int(os.getenv("NOETL_AUTO_RESUME_MIN_READY_WORKERS", "1")),
)
_AUTO_RESUME_MIN_STALE_SECONDS = max(
    0.0,
    float(os.getenv("NOETL_AUTO_RESUME_MIN_STALE_SECONDS", "180")),
)
_AUTO_RESUME_PENDING_ONLY_EVENT_TYPES = frozenset({
    "command.issued",
})

_auto_resume_metrics: dict[str, float] = {
    "attempts_total": 0.0,
    "dependency_ready_total": 0.0,
    "dependency_not_ready_total": 0.0,
    "recoveries_started_total": 0.0,
    "recoveries_completed_total": 0.0,
    "recoveries_failed_total": 0.0,
    "recoveries_cancelled_total": 0.0,
    "recoveries_restarted_total": 0.0,
}


def _inc_metric(name: str, amount: float = 1.0) -> None:
    _auto_resume_metrics[name] = float(_auto_resume_metrics.get(name, 0.0)) + amount


def get_auto_resume_metrics_snapshot() -> dict[str, float]:
    return dict(_auto_resume_metrics)


async def _check_postgres_ready() -> tuple[bool, str]:
    try:
        async with get_pool_connection(timeout=3.0) as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT 1 AS ok")
                row = await cur.fetchone()
                if row and int(row.get("ok", 0)) == 1:
                    return True, "postgres_ok"
        return False, "postgres_no_row"
    except Exception as e:
        return False, f"postgres_error:{e}"


async def _check_nats_ready() -> tuple[bool, str]:
    try:
        # Reuse server's publisher bootstrap and verify active connection.
        from noetl.server.api.v2 import get_nats_publisher

        publisher = await get_nats_publisher()
        nc = getattr(publisher, "_nc", None)
        if nc is None:
            return False, "nats_missing_connection"
        if not bool(getattr(nc, "is_connected", False)):
            return False, "nats_not_connected"
        await nc.flush(timeout=1.0)
        return True, "nats_ok"
    except Exception as e:
        return False, f"nats_error:{e}"


async def _count_ready_workers(max_heartbeat_age_seconds: float) -> int:
    async with get_pool_connection(timeout=3.0) as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT COUNT(*)::int AS ready_workers
                FROM noetl.runtime
                WHERE kind = 'worker_pool'
                  AND status = 'ready'
                  AND heartbeat >= NOW() - (%s * INTERVAL '1 second')
                """,
                (max_heartbeat_age_seconds,),
            )
            row = await cur.fetchone()
            return int((row or {}).get("ready_workers", 0) or 0)


async def _check_worker_ready() -> tuple[bool, str]:
    try:
        ready_workers = await _count_ready_workers(_AUTO_RESUME_WORKER_HEARTBEAT_MAX_AGE_SECONDS)
        if ready_workers >= _AUTO_RESUME_MIN_READY_WORKERS:
            return True, f"workers_ok:{ready_workers}"
        return False, f"workers_insufficient:{ready_workers}"
    except Exception as e:
        return False, f"workers_error:{e}"


async def _check_recovery_dependencies() -> tuple[bool, Dict[str, str]]:
    postgres_ok, postgres_reason = await _check_postgres_ready()
    nats_ok, nats_reason = await _check_nats_ready()
    worker_ok, worker_reason = await _check_worker_ready()
    details = {
        "postgres": postgres_reason,
        "nats": nats_reason,
        "workers": worker_reason,
    }
    return postgres_ok and nats_ok and worker_ok, details


async def _wait_for_dependencies_ready() -> bool:
    timeout_seconds = _AUTO_RESUME_READINESS_TIMEOUT_SECONDS
    poll_seconds = _AUTO_RESUME_READINESS_POLL_SECONDS
    max_attempts = max(1, int(timeout_seconds / poll_seconds))

    for attempt in range(1, max_attempts + 1):
        _inc_metric("attempts_total")
        ready, details = await _check_recovery_dependencies()
        if ready:
            _inc_metric("dependency_ready_total")
            logger.info(
                "[AUTO-RESUME] Dependencies ready (attempt %s/%s): postgres=%s nats=%s workers=%s",
                attempt,
                max_attempts,
                details.get("postgres"),
                details.get("nats"),
                details.get("workers"),
            )
            return True

        _inc_metric("dependency_not_ready_total")
        logger.warning(
            "[AUTO-RESUME] Dependencies not ready (attempt %s/%s): postgres=%s nats=%s workers=%s",
            attempt,
            max_attempts,
            details.get("postgres"),
            details.get("nats"),
            details.get("workers"),
        )
        if attempt < max_attempts:
            await asyncio.sleep(poll_seconds)
    return False


def _extract_workload_from_result(result_obj: Any) -> dict[str, Any]:
    if not isinstance(result_obj, dict):
        return {}
    payload = result_obj
    if "data" in payload and isinstance(payload["data"], dict):
        payload = payload["data"]
    if "result" in payload and isinstance(payload["result"], dict):
        candidate = payload["result"].get("workload")
        if isinstance(candidate, dict):
            return candidate
    candidate = payload.get("workload")
    if isinstance(candidate, dict):
        return candidate
    return {}


def _coerce_utc_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _candidate_stale_age_seconds(candidate: Dict[str, Any], *, now: Optional[datetime] = None) -> Optional[float]:
    now_utc = now or datetime.now(timezone.utc)
    last_event_at = _coerce_utc_datetime(candidate.get("latest_event_at"))
    if last_event_at is None:
        last_event_at = _coerce_utc_datetime(candidate.get("created_at"))
    if last_event_at is None:
        return None
    return max(0.0, (now_utc - last_event_at).total_seconds())


def _should_recover_candidate(candidate: Dict[str, Any], *, now: Optional[datetime] = None) -> bool:
    latest_event_type = str(candidate.get("latest_event_type") or "").strip().lower()
    if latest_event_type in _AUTO_RESUME_PENDING_ONLY_EVENT_TYPES:
        return False

    stale_age_seconds = _candidate_stale_age_seconds(candidate, now=now)
    if stale_age_seconds is None:
        return True
    return stale_age_seconds >= _AUTO_RESUME_MIN_STALE_SECONDS


async def get_execution_status(execution_id: int) -> str:
    """Determine execution status from terminal events."""
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT event_type, status
                FROM noetl.event
                WHERE execution_id = %s
                  AND event_type IN ('playbook.completed', 'playbook.failed', 'execution.cancelled')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (execution_id,),
            )
            row = await cur.fetchone()
            if row:
                if row["event_type"] == "playbook.completed":
                    return "completed"
                if row["event_type"] == "playbook.failed":
                    return "failed"
                if row["event_type"] == "execution.cancelled":
                    return "cancelled"
            return "running"


async def get_recovery_candidates() -> list[Dict[str, Any]]:
    """
    Return recent parent playbooks that may need recovery.

    Parent only: `parent_execution_id IS NULL`.
    """
    fetch_limit = max(
        max(_AUTO_RESUME_MAX_CANDIDATES, 1) * 10,
        max(_AUTO_RESUME_MAX_CANDIDATES, 1),
    )
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT
                    e.execution_id,
                    c.path,
                    e.catalog_id,
                    e.result,
                    e.created_at,
                    latest.event_type AS latest_event_type,
                    latest.created_at AS latest_event_at
                FROM noetl.event e
                JOIN noetl.catalog c ON c.catalog_id = e.catalog_id
                JOIN LATERAL (
                    SELECT ev.event_type, ev.created_at
                    FROM noetl.event ev
                    WHERE ev.execution_id = e.execution_id
                    ORDER BY ev.event_id DESC
                    LIMIT 1
                ) latest ON TRUE
                WHERE e.event_type = 'playbook.initialized'
                  AND e.parent_execution_id IS NULL
                  AND e.created_at > NOW() - (%s * INTERVAL '1 minute')
                  AND NOT EXISTS (
                    SELECT 1
                    FROM noetl.event t
                    WHERE t.execution_id = e.execution_id
                      AND t.event_type IN ('playbook.completed', 'playbook.failed', 'execution.cancelled')
                  )
                ORDER BY e.created_at DESC
                LIMIT %s
                """,
                (_AUTO_RESUME_LOOKBACK_MINUTES, fetch_limit),
            )
            rows = await cur.fetchall()
    return list(rows or [])


async def mark_execution_cancelled(
    execution_id: int,
    reason: str = "Server restart",
    meta_extra: Optional[dict[str, Any]] = None,
    payload_extra: Optional[dict[str, Any]] = None,
) -> bool:
    """Mark an interrupted execution as cancelled."""
    try:
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT catalog_id
                    FROM noetl.event
                    WHERE execution_id = %s
                    ORDER BY event_id ASC
                    LIMIT 1
                    """,
                    (execution_id,),
                )
                row = await cur.fetchone()
                if not row or not row.get("catalog_id"):
                    logger.warning(
                        "[AUTO-RESUME] Could not resolve catalog_id for execution %s; skipping cancel marker",
                        execution_id,
                    )
                    return False

                event_id = await get_snowflake_id()
                cancel_payload: dict[str, Any] = {
                    "reason": reason,
                    "auto_cancelled": True,
                }
                if payload_extra:
                    cancel_payload.update(payload_extra)
                cancel_meta: dict[str, Any] = {
                    "actionable": False,
                    "informative": True,
                    "auto_resume": True,
                }
                if meta_extra:
                    cancel_meta.update(meta_extra)
                await cur.execute(
                    """
                    INSERT INTO noetl.event (
                        execution_id, catalog_id, event_id, event_type,
                        node_id, node_name, status, result, meta, created_at
                    ) VALUES (
                        %s, %s, %s, 'execution.cancelled',
                        %s, %s, 'CANCELLED', %s, %s, NOW()
                    )
                    """,
                    (
                        execution_id,
                        row["catalog_id"],
                        int(event_id),
                        "workflow",
                        "workflow",
                        Json({"status": "CANCELLED", "context": cancel_payload}),
                        Json(cancel_meta),
                    ),
                )
                await conn.commit()

        _inc_metric("recoveries_cancelled_total")
        logger.info("[AUTO-RESUME] Marked execution %s as CANCELLED", execution_id)
        return True
    except Exception as e:
        logger.error("[AUTO-RESUME] Failed to mark execution %s as cancelled: %s", execution_id, e, exc_info=True)
        return False


async def _restart_execution(candidate: Dict[str, Any]) -> Optional[str]:
    """Start a replacement playbook execution for interrupted parent run."""
    try:
        from noetl.server.api.v2 import execute, ExecuteRequest

        workload = _extract_workload_from_result(candidate.get("result"))
        req = ExecuteRequest(
            catalog_id=int(candidate["catalog_id"]),
            payload=workload,
            parent_execution_id=int(candidate["execution_id"]),
        )
        response = await execute(req)
        _inc_metric("recoveries_restarted_total")
        return str(response.execution_id)
    except Exception as e:
        logger.error(
            "[AUTO-RESUME] Restart failed for execution %s (%s): %s",
            candidate.get("execution_id"),
            candidate.get("path"),
            e,
            exc_info=True,
        )
        return None


async def _recover_interrupted_parent_executions(mode: str) -> None:
    candidates = await get_recovery_candidates()
    if not candidates:
        logger.info(
            "[AUTO-RESUME] No interrupted parent executions found in last %s minutes",
            _AUTO_RESUME_LOOKBACK_MINUTES,
        )
        return

    logger.info(
        "[AUTO-RESUME] Found %s interrupted parent execution candidate(s), mode=%s",
        len(candidates),
        mode,
    )
    recovered_candidates = 0
    for candidate in candidates:
        if recovered_candidates >= _AUTO_RESUME_MAX_CANDIDATES:
            break
        execution_id = int(candidate["execution_id"])
        path = str(candidate.get("path") or "")
        stale_age_seconds = _candidate_stale_age_seconds(candidate)
        latest_event_type = str(candidate.get("latest_event_type") or "")
        if not _should_recover_candidate(candidate):
            logger.info(
                "[AUTO-RESUME] Skip execution %s (%s): latest_event_type=%s stale_age_seconds=%s",
                execution_id,
                path,
                latest_event_type or "unknown",
                round(stale_age_seconds, 3) if stale_age_seconds is not None else "unknown",
            )
            continue
        status = await get_execution_status(execution_id)
        if status != "running":
            logger.info(
                "[AUTO-RESUME] Skip execution %s (%s): status=%s",
                execution_id,
                path,
                status,
            )
            continue

        if mode == "restart":
            restarted_execution_id = await _restart_execution(candidate)
            if restarted_execution_id:
                recovered_candidates += 1
                await mark_execution_cancelled(
                    execution_id,
                    reason="Auto-recovery restart launched replacement execution",
                    meta_extra={"restarted_execution_id": restarted_execution_id},
                    payload_extra={"restarted_execution_id": restarted_execution_id},
                )
                logger.info(
                    "[AUTO-RESUME] Restarted execution %s (%s) -> new execution %s",
                    execution_id,
                    path,
                    restarted_execution_id,
                )
            else:
                _inc_metric("recoveries_failed_total")
        else:
            ok = await mark_execution_cancelled(
                execution_id,
                reason="Auto-recovery in cancel mode (restart disabled)",
            )
            if not ok:
                _inc_metric("recoveries_failed_total")
            else:
                recovered_candidates += 1


async def resume_interrupted_executions() -> None:
    """
    Recover interrupted parent executions after readiness checks pass.

    Modes:
    - restart (default): restart interrupted parent and cancel old execution.
    - cancel: only cancel interrupted parent execution.
    """
    if not _AUTO_RESUME_ENABLED:
        logger.info("[AUTO-RESUME] Disabled by NOETL_AUTO_RESUME_ENABLED=false")
        return

    mode = _AUTO_RESUME_MODE if _AUTO_RESUME_MODE in {"restart", "cancel"} else "restart"
    if mode != _AUTO_RESUME_MODE:
        logger.warning(
            "[AUTO-RESUME] Unsupported NOETL_AUTO_RESUME_MODE=%s, defaulting to restart",
            _AUTO_RESUME_MODE,
        )

    try:
        if _AUTO_RESUME_STARTUP_DELAY_SECONDS > 0:
            await asyncio.sleep(_AUTO_RESUME_STARTUP_DELAY_SECONDS)

        ready = await _wait_for_dependencies_ready()
        if not ready:
            logger.error(
                "[AUTO-RESUME] Dependencies not ready within %.1fs, skipping recovery",
                _AUTO_RESUME_READINESS_TIMEOUT_SECONDS,
            )
            return

        _inc_metric("recoveries_started_total")
        await _recover_interrupted_parent_executions(mode=mode)
        _inc_metric("recoveries_completed_total")
    except asyncio.CancelledError:
        logger.info("[AUTO-RESUME] Recovery task cancelled")
        raise
    except Exception as e:
        _inc_metric("recoveries_failed_total")
        logger.error("[AUTO-RESUME] Critical recovery error: %s", e, exc_info=True)
