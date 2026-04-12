import os
import json
import time
import asyncio
import heapq
import math
from dataclasses import dataclass
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from typing import Any, Optional, Literal
from datetime import datetime, timezone
from psycopg.types.json import Json
from psycopg.rows import dict_row
from psycopg_pool import PoolTimeout
from noetl.core.dsl.v2.models import Event
from noetl.core.dsl.v2.engine import ControlFlowEngine, PlaybookRepo, StateStore
from noetl.core.db.pool import get_pool_connection, get_server_pool_stats
from noetl.core.messaging import NATSCommandPublisher
from noetl.core.storage import Scope, default_store, estimate_size
from noetl.claim_policy import decide_reclaim_for_existing_claim
from noetl.server.api.event_queries import PENDING_COMMAND_COUNT_SQL
from noetl.server.api.supervision import supervise_command_issued, supervise_persisted_event
from noetl.core.logger import setup_logger

from .core import *
from .models import *
from .utils import *
from .db import *
_publish_recovery_tasks: set[asyncio.Task] = set()

_publish_recovery_semaphore = asyncio.Semaphore(_COMMAND_PUBLISH_RECOVERY_MAX_CONCURRENCY)

def _track_publish_recovery_task(task: asyncio.Task) -> None:
    _publish_recovery_tasks.add(task)
    task.add_done_callback(_publish_recovery_tasks.discard)

async def shutdown_publish_recovery_tasks() -> None:
    """Cancel and await tracked publish-recovery tasks before pool shutdown."""
    if not _publish_recovery_tasks:
        return
    tasks = list(_publish_recovery_tasks)
    _publish_recovery_tasks.clear()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

def _compute_publish_recovery_delay(delay_seconds: float, event_id: int) -> float:
    if _COMMAND_PUBLISH_RECOVERY_JITTER_SECONDS <= 0:
        return delay_seconds
    jitter_ratio = event_id % 1000 / 1000.0
    return delay_seconds + _COMMAND_PUBLISH_RECOVERY_JITTER_SECONDS * jitter_ratio

async def _command_has_claim_or_terminal(*, execution_id: int, command_id: str) -> bool:
    async with get_pool_connection(timeout=5.0) as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("\n                SELECT EXISTS (\n                    SELECT 1\n                    FROM noetl.event e\n                    WHERE e.execution_id = %s\n                      AND (\n                          (\n                              e.event_type = 'command.claimed'\n                              AND e.meta->>'command_id' = %s\n                          )\n                          OR (\n                              e.event_type = ANY(%s)\n                              AND e.meta->>'command_id' = %s\n                          )\n                          OR e.event_type = ANY(%s)\n                      )\n                ) AS has_claim_or_terminal\n                ", (execution_id, command_id, _COMMAND_TERMINAL_EVENT_TYPES, command_id, _EXECUTION_TERMINAL_EVENT_TYPES))
            row = await cur.fetchone()
    return bool(row and row.get('has_claim_or_terminal'))

async def _fetch_execution_terminal_event(cur, execution_id: int) -> Optional[dict[str, Any]]:
    await cur.execute('\n        SELECT event_type, created_at\n        FROM noetl.event\n        WHERE execution_id = %s\n          AND event_type = ANY(%s)\n        ORDER BY event_id DESC\n        LIMIT 1\n        ', (execution_id, _EXECUTION_TERMINAL_EVENT_TYPES))
    row = await cur.fetchone()
    return row if isinstance(row, dict) else None

async def _recover_unclaimed_command_after_delay(*, execution_id: int, event_id: int, command_id: str, step: str, server_url: str, delay_seconds: float) -> None:
    try:
        await asyncio.sleep(_compute_publish_recovery_delay(delay_seconds, event_id))
        async with _publish_recovery_semaphore:
            if await _command_has_claim_or_terminal(execution_id=execution_id, command_id=command_id):
                logger.debug('[PUBLISH-RECOVERY] Skipping recovery for execution_id=%s command_id=%s; claim or terminal event already exists', execution_id, command_id)
                return
            logger.warning('[PUBLISH-RECOVERY] Re-publishing unclaimed command after %.1fs: execution_id=%s event_id=%s command_id=%s step=%s', delay_seconds, execution_id, event_id, command_id, step)
            nats_pub = await get_nats_publisher()
            await nats_pub.publish_command(execution_id=execution_id, event_id=event_id, command_id=command_id, step=step, server_url=server_url)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error('[PUBLISH-RECOVERY] Failed for execution_id=%s event_id=%s command_id=%s: %s', execution_id, event_id, command_id, exc, exc_info=True)

async def _publish_commands_with_recovery(command_events: list[tuple[int, int, str, str]], *, server_url: str) -> None:
    if not command_events:
        return
    nats_pub = None
    publish_errors: list[Exception] = []
    try:
        nats_pub = await get_nats_publisher()
    except Exception as exc:
        publish_errors.append(exc)
        logger.warning('[PUBLISH-RECOVERY] NATS publisher unavailable before initial publish; scheduling delayed recovery for %d command(s): %s', len(command_events), exc, exc_info=True)
    for execution_id, event_id, command_id, step in command_events:
        if nats_pub is not None:
            try:
                await nats_pub.publish_command(execution_id=execution_id, event_id=event_id, command_id=command_id, step=step, server_url=server_url)
            except Exception as exc:
                publish_errors.append(exc)
                logger.warning('[PUBLISH-RECOVERY] Initial publish failed for execution_id=%s event_id=%s command_id=%s step=%s: %s', execution_id, event_id, command_id, step, exc, exc_info=True)
        recovery_task = asyncio.create_task(_recover_unclaimed_command_after_delay(execution_id=execution_id, event_id=event_id, command_id=command_id, step=step, server_url=server_url, delay_seconds=_COMMAND_PUBLISH_RECOVERY_DELAY_SECONDS), name=f'command-publish-recovery:{execution_id}:{command_id}')
        _track_publish_recovery_task(recovery_task)
    if publish_errors:
        logger.warning('[PUBLISH-RECOVERY] Scheduled delayed recovery for %d command(s) after initial publish failure(s)', len(publish_errors))

__all__ = ['_publish_recovery_tasks', '_publish_recovery_semaphore', '_track_publish_recovery_task', 'shutdown_publish_recovery_tasks', '_compute_publish_recovery_delay', '_command_has_claim_or_terminal', '_fetch_execution_terminal_event', '_recover_unclaimed_command_after_delay', '_publish_commands_with_recovery']
