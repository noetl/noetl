"""Standalone transactional outbox publisher."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Optional

from noetl.core.common import get_pgdb_connection
from noetl.core.db.pool import close_pool, init_pool
from noetl.core.logger import setup_logger
from noetl.core.outbox import ensure_outbox_schema, publish_outbox_batch

logger = setup_logger(__name__, include_location=True)


@dataclass(frozen=True)
class OutboxPublisherSettings:
    batch_size: int = 100
    idle_sleep_seconds: float = 1.0
    error_sleep_seconds: float = 5.0
    once: bool = False


def load_outbox_publisher_settings() -> OutboxPublisherSettings:
    return OutboxPublisherSettings(
        batch_size=max(1, _int_env("NOETL_OUTBOX_PUBLISHER_BATCH_SIZE", 100)),
        idle_sleep_seconds=max(0.05, _float_env("NOETL_OUTBOX_PUBLISHER_IDLE_SLEEP_SECONDS", 1.0)),
        error_sleep_seconds=max(0.05, _float_env("NOETL_OUTBOX_PUBLISHER_ERROR_SLEEP_SECONDS", 5.0)),
        once=_bool_env("NOETL_OUTBOX_PUBLISHER_ONCE", False),
    )


async def run_outbox_publisher(settings: Optional[OutboxPublisherSettings] = None) -> None:
    effective_settings = settings or load_outbox_publisher_settings()
    await init_pool(get_pgdb_connection())
    try:
        await ensure_outbox_schema()
        while True:
            try:
                published = await publish_outbox_batch(limit=effective_settings.batch_size)
                if effective_settings.once:
                    return
                if published <= 0:
                    await asyncio.sleep(effective_settings.idle_sleep_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Outbox publisher iteration failed: %s", exc, exc_info=True)
                if effective_settings.once:
                    raise
                await asyncio.sleep(effective_settings.error_sleep_seconds)
    finally:
        await close_pool()


def run_outbox_publisher_sync(settings: Optional[OutboxPublisherSettings] = None) -> None:
    asyncio.run(run_outbox_publisher(settings=settings))


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return float(value)


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

