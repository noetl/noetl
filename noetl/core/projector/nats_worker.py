"""NATS-backed projector worker entrypoint primitives."""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from noetl.core.logger import setup_logger
from noetl.core.messaging import NATSCommandSubscriber
from noetl.core.projection_store import PostgresProjectionStore, ProjectionStore

from .service import ReplayStateProjector

logger = setup_logger(__name__, include_location=True)


@dataclass(frozen=True)
class ProjectorWorkerSettings:
    """Runtime settings for the event projector consumer."""

    nats_url: str = "nats://noetl:noetl@nats.nats.svc.cluster.local:4222"
    stream_name: str = "NOETL_EVENTS"
    subject: str = "noetl.events.>"
    consumer_name: str = "noetl-projector-0"
    shard_id: str = "noetl-projector-0"
    shard_count: int = 1
    max_inflight: int = 8
    max_ack_pending: int = 64
    fetch_timeout_seconds: float = 30.0
    fetch_heartbeat_seconds: float = 5.0

    @property
    def shard_index(self) -> int:
        return _parse_shard_index(self.shard_id)


def load_projector_worker_settings() -> ProjectorWorkerSettings:
    """Load projector settings from environment variables."""

    shard_id = (
        os.getenv("NOETL_PROJECTOR_SHARD_ID")
        or os.getenv("NOETL_SHARD_ID")
        or os.getenv("HOSTNAME")
        or "noetl-projector-0"
    )
    consumer_name = os.getenv("NOETL_PROJECTOR_NATS_CONSUMER") or shard_id
    return ProjectorWorkerSettings(
        nats_url=os.getenv("NOETL_PROJECTOR_NATS_URL") or os.getenv("NATS_URL") or ProjectorWorkerSettings.nats_url,
        stream_name=os.getenv("NOETL_PROJECTOR_NATS_STREAM") or "NOETL_EVENTS",
        subject=os.getenv("NOETL_PROJECTOR_NATS_SUBJECT") or "noetl.events.>",
        consumer_name=consumer_name,
        shard_id=shard_id,
        shard_count=max(1, _int_env("NOETL_PROJECTOR_SHARD_COUNT", 1)),
        max_inflight=max(1, _int_env("NOETL_PROJECTOR_MAX_INFLIGHT", 8)),
        max_ack_pending=max(1, _int_env("NOETL_PROJECTOR_NATS_MAX_ACK_PENDING", 64)),
        fetch_timeout_seconds=max(0.1, _float_env("NOETL_PROJECTOR_NATS_FETCH_TIMEOUT_SECONDS", 30.0)),
        fetch_heartbeat_seconds=max(0.1, _float_env("NOETL_PROJECTOR_NATS_FETCH_HEARTBEAT_SECONDS", 5.0)),
    )


class NATSProjectorWorker:
    """Consume event envelopes and update replayable projections."""

    def __init__(
        self,
        *,
        projection_store: Optional[ProjectionStore] = None,
        settings: Optional[ProjectorWorkerSettings] = None,
        projection: str = "all",
    ) -> None:
        self.settings = settings or load_projector_worker_settings()
        self.projection_store = projection_store or PostgresProjectionStore()
        self.projector = ReplayStateProjector(self.projection_store, projection=projection)
        self._subscriber: Optional[NATSCommandSubscriber] = None

    async def start(self) -> None:
        """Start the durable NATS pull consumer."""

        ensure_schema = getattr(self.projection_store, "ensure_schema", None)
        if callable(ensure_schema):
            await ensure_schema()

        self._subscriber = NATSCommandSubscriber(
            nats_url=self.settings.nats_url,
            subject=self.settings.subject,
            consumer_name=self.settings.consumer_name,
            stream_name=self.settings.stream_name,
            max_inflight=self.settings.max_inflight,
            max_ack_pending=self.settings.max_ack_pending,
            fetch_timeout=self.settings.fetch_timeout_seconds,
            fetch_heartbeat=self.settings.fetch_heartbeat_seconds,
        )
        await self._subscriber.connect()
        logger.info(
            "Projector %s consuming %s/%s as %s",
            self.settings.shard_id,
            self.settings.stream_name,
            self.settings.subject,
            self.settings.consumer_name,
        )
        await self._subscriber.subscribe(self.handle_notification)

    async def close(self) -> None:
        if self._subscriber is not None:
            await self._subscriber.close()

    async def handle_notification(self, notification: dict[str, Any]) -> str:
        """Project one NATS notification and return an ack action."""

        events = [
            event
            for event in _extract_events(notification)
            if self._owns_event(event)
        ]
        if not events:
            return "ack"

        written = await self.projector.project(events)
        logger.debug(
            "Projector %s folded %s events into %s projection records",
            self.settings.shard_id,
            len(events),
            len(written),
        )
        return "ack"

    def _owns_event(self, event: dict[str, Any]) -> bool:
        if self.settings.shard_count <= 1:
            return True
        execution_id = event.get("execution_id")
        if execution_id is None:
            return False
        try:
            return int(execution_id) % self.settings.shard_count == self.settings.shard_index
        except (TypeError, ValueError):
            return False


async def run_projector_worker(settings: Optional[ProjectorWorkerSettings] = None) -> None:
    worker = NATSProjectorWorker(settings=settings)
    try:
        await worker.start()
    finally:
        await worker.close()


def run_projector_worker_sync(settings: Optional[ProjectorWorkerSettings] = None) -> None:
    asyncio.run(run_projector_worker(settings=settings))


def _extract_events(notification: dict[str, Any]) -> list[dict[str, Any]]:
    events = notification.get("events")
    if isinstance(events, list):
        return [dict(event) for event in events if isinstance(event, dict)]

    event = notification.get("event")
    if isinstance(event, dict):
        return [dict(event)]

    if notification.get("event_type") and notification.get("execution_id") is not None:
        return [dict(notification)]

    return []


def _parse_shard_index(shard_id: str) -> int:
    match = re.search(r"(\d+)$", shard_id or "")
    return int(match.group(1)) if match else 0


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
