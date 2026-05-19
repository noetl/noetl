from __future__ import annotations

import os
from typing import Any

from noetl.core.logger import setup_logger
from noetl.core.messaging import NATSEventPublisher
from noetl.core.outbox import enqueue_outbox, publish_outbox_batch

logger = setup_logger(__name__, include_location=True)
_executor_event_subject_publisher: NATSEventPublisher | None = None


def event_mirror_enabled() -> bool:
    return os.getenv("NOETL_EVENT_MIRROR_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def executor_event_subject(event: dict[str, Any]) -> str:
    global _executor_event_subject_publisher
    if _executor_event_subject_publisher is None:
        _executor_event_subject_publisher = NATSEventPublisher()
    return _executor_event_subject_publisher.subject_for_event(event)


async def enqueue_executor_outbox(cur: Any, event: dict[str, Any]) -> None:
    if not event_mirror_enabled():
        return
    await enqueue_outbox(cur, event, subject=executor_event_subject(event))


async def drain_executor_outbox() -> None:
    if not event_mirror_enabled():
        return
    try:
        limit = int(os.getenv("NOETL_EXECUTOR_OUTBOX_DRAIN_LIMIT", "100"))
        await publish_outbox_batch(limit=limit)
    except Exception as exc:
        logger.warning("Executor outbox drain failed: %s", exc)
