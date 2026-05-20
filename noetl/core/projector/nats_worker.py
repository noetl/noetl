"""NATS-backed projector worker entrypoint primitives."""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from psycopg import errors as pg_errors

from noetl.core.common import get_pgdb_connection
from noetl.core.db.pool import close_pool, init_pool
from noetl.core.logger import setup_logger
from noetl.core.messaging import NATSCommandSubscriber
from noetl.core.projection_store import PostgresProjectionStore, ProjectionStore
from noetl.core.storage.arrow_ipc import arrow_feather_to_rows

from .metrics import ProjectorMetrics, start_projector_metrics_server
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
    metrics_host: str = "0.0.0.0"
    metrics_port: Optional[int] = None

    def __post_init__(self) -> None:
        if self.shard_count < 1:
            raise ValueError("projector shard_count must be at least 1")
        if self.shard_index >= self.shard_count:
            raise ValueError(
                "projector shard index must be less than shard_count "
                f"(shard_id={self.shard_id!r}, shard_index={self.shard_index}, shard_count={self.shard_count})"
            )
        if self.max_inflight < 1:
            raise ValueError("projector max_inflight must be at least 1")
        if self.max_ack_pending < 1:
            raise ValueError("projector max_ack_pending must be at least 1")
        if self.fetch_timeout_seconds <= 0:
            raise ValueError("projector fetch_timeout_seconds must be positive")
        if self.fetch_heartbeat_seconds <= 0:
            raise ValueError("projector fetch_heartbeat_seconds must be positive")
        if self.metrics_port is not None and self.metrics_port <= 0:
            raise ValueError("projector metrics_port must be positive when set")

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
        shard_count=_int_env("NOETL_PROJECTOR_SHARD_COUNT", 1),
        max_inflight=_int_env("NOETL_PROJECTOR_MAX_INFLIGHT", 8),
        max_ack_pending=_int_env("NOETL_PROJECTOR_NATS_MAX_ACK_PENDING", 64),
        fetch_timeout_seconds=_float_env("NOETL_PROJECTOR_NATS_FETCH_TIMEOUT_SECONDS", 30.0),
        fetch_heartbeat_seconds=_float_env("NOETL_PROJECTOR_NATS_FETCH_HEARTBEAT_SECONDS", 5.0),
        metrics_host=os.getenv("NOETL_PROJECTOR_METRICS_HOST") or "0.0.0.0",
        metrics_port=_optional_int_env("NOETL_PROJECTOR_METRICS_PORT"),
    )


class NATSProjectorWorker:
    """Consume event envelopes and update replayable projections."""

    def __init__(
        self,
        *,
        projection_store: Optional[ProjectionStore] = None,
        settings: Optional[ProjectorWorkerSettings] = None,
        projection: str = "all",
        metrics: Optional[ProjectorMetrics] = None,
    ) -> None:
        self.settings = settings or load_projector_worker_settings()
        self.projection_store = projection_store or PostgresProjectionStore()
        self.projector = ReplayStateProjector(self.projection_store, projection=projection)
        self.metrics = metrics or ProjectorMetrics()
        self._subscriber: Optional[NATSCommandSubscriber] = None

    async def start(self) -> None:
        """Start the durable NATS pull consumer."""

        ensure_schema = getattr(self.projection_store, "ensure_schema", None)
        if callable(ensure_schema):
            try:
                await ensure_schema()
            except pg_errors.InsufficientPrivilege:
                logger.warning(
                    "Projector %s cannot run projection DDL; continuing with existing schema",
                    self.settings.shard_id,
                )

        self._subscriber = NATSCommandSubscriber(
            nats_url=self.settings.nats_url,
            subject=self.settings.subject,
            consumer_name=self.settings.consumer_name,
            stream_name=self.settings.stream_name,
            max_inflight=self.settings.max_inflight,
            max_ack_pending=self.settings.max_ack_pending,
            fetch_timeout=self.settings.fetch_timeout_seconds,
            fetch_heartbeat=self.settings.fetch_heartbeat_seconds,
            message_decoder=self._decode_notification,
            message_action_observer=self.metrics.record_message_action,
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

    def _decode_notification(self, payload: bytes) -> dict[str, Any]:
        try:
            return decode_projector_notification(payload)
        except Exception:
            self.metrics.record_decode_error()
            raise

    async def handle_notification(self, notification: dict[str, Any]) -> str:
        """Project one NATS notification and return an ack action."""

        extracted_events = _extract_events(notification)
        events: list[dict[str, Any]] = []
        unowned_events = 0
        unshardable_events = 0
        for event in extracted_events:
            decision = self._shard_decision(event)
            if decision == "owned":
                events.append(event)
            elif decision == "unowned":
                unowned_events += 1
            else:
                unshardable_events += 1
        if not events:
            self.metrics.record_notification(
                extracted_events=len(extracted_events),
                owned_events=0,
                projection_records=0,
                unowned_events=unowned_events,
                unshardable_events=unshardable_events,
            )
            return "ack"

        try:
            projection_group_count = _projection_group_count(events)
            written = await self.projector.project(events)
        except Exception:
            self.metrics.record_error()
            raise
        self.metrics.record_notification(
            extracted_events=len(extracted_events),
            owned_events=len(events),
            projection_records=len(written),
            unowned_events=unowned_events,
            unshardable_events=unshardable_events,
            stale_projection_records=max(0, projection_group_count - len(written)),
        )
        self.metrics.record_projection_checkpoints(written)
        logger.debug(
            "Projector %s folded %s events into %s projection records",
            self.settings.shard_id,
            len(events),
            len(written),
        )
        return "ack"

    def _owns_event(self, event: dict[str, Any]) -> bool:
        return self._shard_decision(event) == "owned"

    def _shard_decision(self, event: dict[str, Any]) -> str:
        if self.settings.shard_count <= 1:
            return "owned"
        execution_id = event.get("execution_id")
        if execution_id is None:
            return "unshardable"
        try:
            return (
                "owned"
                if int(execution_id) % self.settings.shard_count == self.settings.shard_index
                else "unowned"
            )
        except (TypeError, ValueError):
            return "unshardable"


async def run_projector_worker(settings: Optional[ProjectorWorkerSettings] = None) -> None:
    effective_settings = settings or load_projector_worker_settings()
    await init_pool(get_pgdb_connection())
    worker = NATSProjectorWorker(settings=effective_settings)
    metrics_server = None
    if effective_settings.metrics_port:
        metrics_server = start_projector_metrics_server(
            worker.metrics,
            host=effective_settings.metrics_host,
            port=effective_settings.metrics_port,
            labels={
                "shard_id": effective_settings.shard_id,
                "shard_index": str(effective_settings.shard_index),
                "shard_count": str(effective_settings.shard_count),
                "consumer": effective_settings.consumer_name,
                "stream": effective_settings.stream_name,
                "subject": effective_settings.subject,
            },
        )
        logger.info(
            "Projector %s exposing metrics on %s:%s",
            effective_settings.shard_id,
            effective_settings.metrics_host,
            effective_settings.metrics_port,
        )
    try:
        await worker.start()
    finally:
        if metrics_server is not None:
            metrics_server.shutdown()
            metrics_server.server_close()
        await worker.close()
        await close_pool()


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


def _projection_group_count(events: Iterable[dict[str, Any]]) -> int:
    groups: set[tuple[str, str, int]] = set()
    for event in events:
        execution_id = event.get("execution_id")
        if execution_id is None:
            continue
        try:
            parsed_execution_id = int(execution_id)
        except (TypeError, ValueError):
            continue
        groups.add(
            (
                str(event.get("tenant_id") or "default"),
                str(event.get("organization_id") or "default"),
                parsed_execution_id,
            )
        )
    return len(groups)


def decode_projector_notification(payload: bytes) -> dict[str, Any]:
    """Decode projector notifications from JSON or Arrow Feather outbox payloads."""

    try:
        decoded = json.loads(payload.decode("utf-8"))
        if isinstance(decoded, dict):
            return decoded
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass

    rows = arrow_feather_to_rows(payload)
    events = [dict(row) for row in rows if isinstance(row, dict)]
    if len(events) == 1:
        return events[0]
    return {"events": events}


def _parse_shard_index(shard_id: str) -> int:
    match = re.search(r"(\d+)$", shard_id or "")
    return int(match.group(1)) if match else 0


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


def _optional_int_env(name: str) -> Optional[int]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    return int(value)


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return float(value)
