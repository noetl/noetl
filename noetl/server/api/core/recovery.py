import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Dict
from .core import get_nats_publisher, logger

_COMMAND_PUBLISH_RECOVERY_DELAY_SECONDS = float(os.getenv("NOETL_COMMAND_PUBLISH_RECOVERY_DELAY_SECONDS", "30.0"))
_PUBLISH_RECOVERY_TASKS: set[asyncio.Task] = set()

def _track_publish_recovery_task(task: asyncio.Task) -> None:
    _PUBLISH_RECOVERY_TASKS.add(task)
    task.add_done_callback(_PUBLISH_RECOVERY_TASKS.discard)

async def shutdown_publish_recovery_tasks() -> None:
    if not _PUBLISH_RECOVERY_TASKS: return
    tasks = list(_PUBLISH_RECOVERY_TASKS); _PUBLISH_RECOVERY_TASKS.clear()
    for t in tasks: t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

async def _recover_unclaimed_command_after_delay(execution_id: int, event_id: int, command_id: str, step: str, server_url: str, delay_seconds: float) -> None:
    await asyncio.sleep(delay_seconds)
    try:
        from noetl.core.db.pool import get_pool_connection
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT count(*) AS total
                    FROM noetl.command
                    WHERE execution_id = %s
                      AND command_id = %s
                      AND status IN ('CLAIMED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')
                    """,
                    (execution_id, int(command_id)),
                )
                if (await cur.fetchone() or {'count': 0}).get('total', 0) > 0: return
        logger.warning("[PUBLISH-RECOVERY] Command unclaimed after %.1fs; re-publishing execution_id=%s command_id=%s", delay_seconds, execution_id, command_id)
        nats_pub = await get_nats_publisher()
        await nats_pub.publish_command(execution_id=execution_id, event_id=event_id, command_id=command_id, step=step, server_url=server_url)
    except Exception as exc:
        logger.error("[PUBLISH-RECOVERY] Recovery failed for %s: %s", command_id, exc, exc_info=True)

async def _publish_commands_with_recovery(command_events: list[tuple[int, int, str, str]], *, server_url: str) -> None:
    if not command_events: return
    nats_pub = None
    try:
        nats_pub = await get_nats_publisher()
    except Exception as exc:
        logger.warning("[PUBLISH-RECOVERY] NATS publisher unavailable; scheduling delayed recovery: %s", exc)

    async def _safe_publish(exec_id, evt_id, cid, step):
        if nats_pub:
            try:
                await nats_pub.publish_command(execution_id=exec_id, event_id=evt_id, command_id=cid, step=step, server_url=server_url)
            except Exception as exc:
                logger.warning("[PUBLISH-RECOVERY] Initial publish failed for %s: %s", cid, exc)
        
        recovery_task = asyncio.create_task(
            _recover_unclaimed_command_after_delay(
                execution_id=exec_id, event_id=evt_id, command_id=cid,
                step=step, server_url=server_url, delay_seconds=_COMMAND_PUBLISH_RECOVERY_DELAY_SECONDS
            ),
            name=f"command-publish-recovery:{exec_id}:{cid}",
        )
        _track_publish_recovery_task(recovery_task)

    publish_semaphore = asyncio.Semaphore(50) # Max 50 parallel NATS publishes
    async def _sem_publish(args):
        async with publish_semaphore:
            await _safe_publish(*args)
            
    await asyncio.gather(*[_sem_publish(args) for args in command_events])
