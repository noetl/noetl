"""
NATS JetStream client for NoETL command notifications.

Architecture:
- Server publishes lightweight command notifications to NATS subject
- Workers subscribe and fetch full command details from queue API
- Workers execute and emit events back to server

Performance tuning:
- Process messages in background tasks (don't block fetch loop)
- Ack AFTER processing outcome is known (preserve redelivery on transient failures)
- Database advisory locks handle exactly-once processing
"""

import asyncio
import json
import math
import re
import time
from contextlib import suppress
from typing import Any, Optional, Callable, Awaitable
import nats
from nats.js import JetStreamContext
from nats.js.api import StreamConfig, ConsumerConfig
from nats.aio.client import Client as NATSClient

from noetl.core.logger import setup_logger
from noetl.core.sanitize import redact_url_credentials

logger = setup_logger(__name__, include_location=True)
_MAX_CALLBACK_NAK_DELAY_SECONDS = 3600.0
_EVENT_SUBJECT_TOKEN_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def _subject_token(value: Any, default: str = "default") -> str:
    token = _EVENT_SUBJECT_TOKEN_RE.sub("-", str(value or default).strip()).strip("-")
    return token or default


class NATSCommandPublisher:
    """
    Publisher for command notifications.

    Server uses this to notify workers of new commands.
    """

    def __init__(
        self,
        nats_url: Optional[str] = None,
        subject: Optional[str] = None,
        stream_name: Optional[str] = None
    ):
        from noetl.core.config import get_worker_settings
        ws = get_worker_settings()
        self.nats_url = nats_url or ws.nats_url
        self.subject = subject or ws.nats_subject
        self.stream_name = stream_name or ws.nats_stream
        self._nc: Optional[NATSClient] = None
        self._js: Optional[JetStreamContext] = None
        self._connect_lock = asyncio.Lock()

    def _is_connected(self) -> bool:
        return bool(
            self._nc
            and getattr(self._nc, "is_connected", False)
            and not getattr(self._nc, "is_closed", False)
            and self._js is not None
        )

    async def _reset_connection_state(self) -> None:
        nc = self._nc
        self._nc = None
        self._js = None
        if nc is not None:
            try:
                await nc.close()
            except Exception:
                logger.debug("Ignoring NATS close failure during reset", exc_info=True)

    async def ensure_connected(self, force: bool = False) -> None:
        if not force and self._is_connected():
            return

        async with self._connect_lock:
            if force:
                await self._reset_connection_state()
            else:
                if self._is_connected():
                    return
                if self._nc is not None or self._js is not None:
                    await self._reset_connection_state()
            await self.connect()

    async def _publish_payload(self, payload: bytes, *, subject: Optional[str] = None) -> None:
        """Publish ``payload`` to ``subject`` (defaults to ``self.subject``).

        The optional ``subject`` parameter is the hook point for the
        pool-routing work in noetl/ai-meta#42 — :meth:`publish_command`
        derives a per-tool-kind subject when routing is enabled and
        passes it through here.  Callers that don't care about routing
        (e.g. internal control messages) keep using ``self.subject`` by
        omitting the argument.
        """
        if not self._js:
            raise RuntimeError("Not connected to NATS")
        await self._js.publish(subject or self.subject, payload)

    async def connect(self):
        """Connect to NATS and setup JetStream."""
        try:
            self._nc = await nats.connect(self.nats_url)
            self._js = self._nc.jetstream()

            from noetl.core.runtime.pool_routing import command_stream_subjects
            desired_subjects = command_stream_subjects(self.subject)

            # Ensure stream exists with the widened subject list (legacy
            # bare subject + the hierarchical wildcard for per-pool
            # routing; see noetl/ai-meta#42 PR-2a).  Both shapes are
            # required during the transition: bare for today's publishes
            # while the routing flag is off, wildcard for the routed
            # publishes that land at PR-5 cutover.
            try:
                info = await self._js.stream_info(self.stream_name)
                current_subjects = list(getattr(info.config, "subjects", None) or [])
                missing = [s for s in desired_subjects if s not in current_subjects]
                if missing:
                    info.config.subjects = current_subjects + missing
                    await self._js.update_stream(config=info.config)
                    logger.info(
                        "Widened %s stream subjects with %s for pool routing (noetl/ai-meta#42)",
                        self.stream_name,
                        missing,
                    )
                else:
                    logger.debug(f"Using existing {self.stream_name} stream")
            except Exception:
                # Create stream if it doesn't exist
                await self._js.add_stream(
                    name=self.stream_name,
                    subjects=desired_subjects,
                    max_age=3600,  # 1 hour retention
                    storage="memory"  # Memory for low latency
                )
                logger.info(
                    "Created stream %s with subjects=%s | connected to NATS at %s",
                    self.stream_name,
                    desired_subjects,
                    redact_url_credentials(self.nats_url),
                )

        except Exception as e:
            logger.error(f"Failed to connect to NATS: {e}")
            raise

    async def publish_command(
        self,
        execution_id: int,
        event_id: int,
        command_id: str,
        step: str,
        server_url: str,
        tool_kind: Optional[str] = None,
        playbook_path: Optional[str] = None,
    ):
        """
        Publish command notification to NATS.

        Event-driven approach:
        - event_id: Points to command.issued event with full command details
        - command_id: Unique identifier for atomic claiming
        - Workers claim by emitting command.claimed event (idempotent)

        ``tool_kind`` is the playbook step's ``tool.kind`` value — when
        the pool-routing scheme is enabled (see
        :func:`noetl.core.runtime.pool_routing.is_routing_enabled`), the
        subject is derived as ``<base>.<pool>.<execution_id>`` so that
        Python-only kinds (e.g. ``agent``) land on a consumer the Rust
        pool doesn't subscribe to.  Until the cutover env flag flips,
        this argument is captured + threaded through but the legacy
        subject is used verbatim — no behaviour change.  See
        noetl/ai-meta#42 for the full plan.

        ``playbook_path`` is the catalog path of the playbook issuing
        the command.  When set + the path starts with a privileged
        prefix (today: ``system/``), the subject routes to a
        dedicated pool segment regardless of ``tool_kind``.  Lets the
        system worker pool claim ``system/outbox_publisher`` commands
        even though they use the generic ``tool: http`` /
        ``tool: nats`` kinds.  See noetl/ai-meta#46 Phase 2.a.2.
        """
        await self.ensure_connected()

        from noetl.core.runtime.pool_routing import route_subject
        subject = route_subject(
            self.subject,
            tool_kind,
            execution_id,
            playbook_path=playbook_path,
        )

        message = {
            "execution_id": execution_id,
            "event_id": event_id,
            "command_id": command_id,
            "step": step,
            "server_url": server_url
        }
        payload = json.dumps(message).encode()

        try:
            await self._publish_payload(payload, subject=subject)
            logger.debug(f"Published command notification: event_id={event_id} command_id={command_id}")

        except Exception as e:
            logger.warning(
                "Failed to publish command event_id=%s command_id=%s on first attempt: %s. Retrying after reconnect.",
                event_id,
                command_id,
                e,
            )
            await self.ensure_connected(force=True)
            try:
                await self._publish_payload(payload, subject=subject)
                logger.info(
                    "Published command notification after reconnect: event_id=%s command_id=%s",
                    event_id,
                    command_id,
                )
            except Exception as retry_error:
                logger.error(
                    "Failed to publish command after reconnect: event_id=%s command_id=%s error=%s",
                    event_id,
                    command_id,
                    retry_error,
                    exc_info=True,
                )
                raise

    async def close(self):
        """Close NATS connection."""
        if self._nc:
            await self._nc.close()
            logger.info("NATS connection closed")


class NATSEventPublisher(NATSCommandPublisher):
    """Publisher for canonical event envelopes mirrored to JetStream."""

    def __init__(
        self,
        nats_url: Optional[str] = None,
        subject_prefix: Optional[str] = None,
        stream_name: Optional[str] = None,
        shard_count: int = 1,
    ):
        import os

        super().__init__(
            nats_url=nats_url or os.getenv("NOETL_EVENT_NATS_URL") or os.getenv("NATS_URL"),
            subject=subject_prefix or os.getenv("NOETL_EVENT_NATS_SUBJECT_PREFIX") or "noetl.events",
            stream_name=stream_name or os.getenv("NOETL_EVENT_NATS_STREAM") or "NOETL_EVENTS",
        )
        self.subject_prefix = self.subject.rstrip(".>")
        self.shard_count = max(1, int(shard_count or os.getenv("NOETL_EVENT_NATS_SHARD_COUNT", "1")))

    async def connect(self):
        """Connect to NATS and ensure the event mirror stream exists."""

        try:
            self._nc = await nats.connect(self.nats_url)
            self._js = self._nc.jetstream()
            try:
                await self._js.stream_info(self.stream_name)
                logger.debug("Using existing %s stream", self.stream_name)
            except Exception:
                await self._js.add_stream(
                    name=self.stream_name,
                    subjects=[f"{self.subject_prefix}.>"],
                    max_age=86400,
                    storage="file",
                )
                logger.info("Created event stream %s for %s.>", self.stream_name, self.subject_prefix)
        except Exception as exc:
            logger.error("Failed to connect event publisher to NATS: %s", exc)
            raise

    def subject_for_event(self, event: dict[str, Any]) -> str:
        execution_id = event.get("execution_id") or "none"
        shard = 0
        try:
            shard = int(execution_id) % self.shard_count
        except (TypeError, ValueError):
            shard = 0
        return ".".join(
            [
                self.subject_prefix,
                _subject_token(event.get("tenant_id")),
                _subject_token(event.get("organization_id")),
                _subject_token(execution_id, "none"),
                str(shard),
            ]
        )

    async def _publish_event_payload(self, subject: str, payload: bytes) -> None:
        if not self._js:
            raise RuntimeError("Not connected to NATS")
        await self._js.publish(subject, payload)

    async def publish_event(self, event: dict[str, Any]) -> None:
        """Publish a canonical event envelope for projector fan-out."""

        await self.ensure_connected()
        subject = self.subject_for_event(event)
        payload = json.dumps(event, default=str, sort_keys=True, separators=(",", ":")).encode("utf-8")
        try:
            await self._publish_event_payload(subject, payload)
            logger.debug("Published event mirror: subject=%s event_id=%s", subject, event.get("event_id"))
        except Exception as exc:
            logger.warning(
                "Failed to publish event mirror event_id=%s on first attempt: %s. Retrying after reconnect.",
                event.get("event_id"),
                exc,
            )
            await self.ensure_connected(force=True)
            await self._publish_event_payload(subject, payload)


class NATSCommandSubscriber:
    """
    Subscriber for command notifications.

    Workers use this to receive command notifications from server.

    Performance optimizations:
    - Process in background task (don't block fetch loop)
    - Ack only after callback outcome to preserve queue-based backpressure/retry
    - Exactly-once handled by database advisory locks
    """

    def __init__(
        self,
        nats_url: Optional[str] = None,
        subject: Optional[str] = None,
        consumer_name: Optional[str] = None,
        stream_name: Optional[str] = None,
        max_inflight: Optional[int] = None,
        max_ack_pending: Optional[int] = None,
        fetch_timeout: Optional[float] = None,
        fetch_heartbeat: Optional[float] = None,
        callback_timeout_seconds: Optional[float] = None,
        message_decoder: Optional[Callable[[bytes], dict[str, Any]]] = None,
        message_action_observer: Optional[Callable[[str, Optional[float]], None]] = None,
        filter_subject: Optional[str] = None,
    ):
        from noetl.core.config import get_worker_settings
        ws = get_worker_settings()
        self.nats_url = nats_url or ws.nats_url
        self.subject = subject or ws.nats_subject
        self.consumer_name = consumer_name or ws.nats_consumer
        self.stream_name = stream_name or ws.nats_stream
        # Optional consumer-side filter subject for per-pool routing
        # (noetl/ai-meta#42 PR-2b).  None means the consumer sees all
        # messages on the stream — that's the legacy single-consumer
        # shape.  A subject pattern like ``noetl.commands.shared.>``
        # makes JetStream filter at the broker, so the Rust worker
        # never even sees Python-only commands.
        self.filter_subject = filter_subject
        self.max_inflight = max(1, int(max_inflight or ws.max_inflight_commands))
        self.max_ack_pending = max(1, int(max_ack_pending or ws.nats_max_ack_pending))
        self.fetch_timeout = float(fetch_timeout if fetch_timeout is not None else ws.nats_fetch_timeout_seconds)
        self.fetch_heartbeat = float(fetch_heartbeat if fetch_heartbeat is not None else ws.nats_fetch_heartbeat_seconds)
        self.callback_timeout_seconds = float(
            callback_timeout_seconds
            if callback_timeout_seconds is not None
            else ws.command_timeout_seconds
        )
        self.callback_hard_timeout_seconds = max(
            self.callback_timeout_seconds * 4.0,
            self._effective_ack_wait_seconds(),
        )
        self.callback_progress_interval_seconds = max(
            5.0,
            min(30.0, self.callback_timeout_seconds / 4.0),
        )
        self._message_decoder = message_decoder or self._decode_json_message
        self._message_action_observer = message_action_observer
        self._nc: Optional[NATSClient] = None
        self._js: Optional[JetStreamContext] = None
        self._subscription = None
        self._background_tasks: set = set()
        self._inflight_semaphore = asyncio.Semaphore(self.max_inflight)
        self._throttle_hits = 0
        self._fetch_recovery_last_attempt = 0.0

    def _record_message_action(self, action: str, delay_seconds: Optional[float] = None) -> None:
        if self._message_action_observer is None:
            return
        try:
            self._message_action_observer(action, delay_seconds)
        except Exception:
            logger.debug("Ignoring NATS message action observer failure", exc_info=True)

    async def _recover_fetch_subscription(self) -> None:
        """Recreate the durable pull subscription after runtime drift."""
        if not self._js:
            raise RuntimeError("Not connected to NATS")

        now = time.monotonic()
        if now - self._fetch_recovery_last_attempt < 30.0:
            return
        self._fetch_recovery_last_attempt = now

        logger.warning(
            "Attempting to recover NATS pull subscription for stream=%s consumer=%s",
            self.stream_name,
            self.consumer_name,
        )
        await self._ensure_consumer()
        self._subscription = await self._js.pull_subscribe(
            self.subject,
            durable=self.consumer_name,
        )
        logger.info(
            "Recovered NATS pull subscription for stream=%s consumer=%s",
            self.stream_name,
            self.consumer_name,
        )

    @staticmethod
    def _decode_json_message(payload: bytes) -> dict[str, Any]:
        return json.loads(payload.decode("utf-8"))

    @staticmethod
    def _effective_ack_wait_seconds() -> float:
        from noetl.core.config import get_worker_settings
        ws = get_worker_settings()
        minimum_ack_wait_seconds = float(ws.command_timeout_seconds) + float(ws.nats_ack_wait_buffer_seconds)
        return max(float(ws.nats_ack_wait_seconds), minimum_ack_wait_seconds)

    async def _keep_message_in_progress(
        self,
        msg,
        stop_event: asyncio.Event,
        interval_seconds: Optional[float] = None,
    ) -> None:
        """
        Periodically extend the JetStream ack deadline while callback work is active.

        This prevents long-running commands from being redelivered mid-flight.
        """
        interval = float(
            interval_seconds
            if interval_seconds is not None
            else self.callback_progress_interval_seconds
        )
        if interval <= 0:
            return

        while True:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
                return
            except asyncio.TimeoutError:
                try:
                    await msg.in_progress()
                except Exception:
                    logger.warning("Failed to send in-progress ack for message", exc_info=True)
                    return

    async def _run_callback_with_message_heartbeat(
        self,
        callback: Callable[[dict], Awaitable[Optional[str]]],
        data: dict,
        msg,
    ) -> Optional[str]:
        """
        Run the subscriber callback with JetStream heartbeat extension and a hard timeout.

        The hard timeout is intentionally much larger than the nominal command timeout so
        long-running but healthy callbacks keep their lease, while truly stuck callbacks
        still get cancelled and released.
        """
        progress_stop = asyncio.Event()
        progress_task = asyncio.create_task(
            self._keep_message_in_progress(msg, progress_stop)
        )
        callback_task = asyncio.create_task(callback(data))
        try:
            return await asyncio.wait_for(
                callback_task,
                timeout=self.callback_hard_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.error(
                "Command callback exceeded hard timeout after %.1fs; cancelling and NAKing for redelivery",
                self.callback_hard_timeout_seconds,
            )
            callback_task.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.wait_for(callback_task, timeout=5.0)
            raise
        finally:
            progress_stop.set()
            progress_task.cancel()
            with suppress(asyncio.CancelledError):
                await progress_task

    @staticmethod
    def _is_not_found_error(exc: Exception) -> bool:
        """Best-effort detection for JetStream not-found responses."""
        message = str(exc).lower()
        return (
            "not found" in message
            or "404" in message
            or "consumer does not exist" in message
            or "consumer not found" in message
        )

    @staticmethod
    def _parse_callback_action(action: object) -> tuple[str, Optional[float]]:
        if not isinstance(action, str):
            logger.warning(
                "Callback returned non-string action (%s); defaulting to NAK",
                type(action).__name__,
            )
            return "nak", None

        normalized = action.strip().lower()
        if normalized in {"ack", "nak", "term"}:
            return normalized, None

        if normalized.startswith("nak:"):
            _, _, raw_delay = normalized.partition(":")
            try:
                delay_seconds = float(raw_delay.strip())
            except (TypeError, ValueError):
                logger.warning(
                    "Callback returned invalid delayed NAK action '%s'; defaulting to immediate NAK",
                    action,
                )
                return "nak", None
            if not math.isfinite(delay_seconds):
                logger.warning(
                    "Callback returned non-finite delayed NAK '%s'; defaulting to immediate NAK",
                    action,
                )
                return "nak", None
            if delay_seconds > 0:
                if delay_seconds > _MAX_CALLBACK_NAK_DELAY_SECONDS:
                    logger.warning(
                        "Callback returned delayed NAK '%s' above %.1fs cap; clamping",
                        action,
                        _MAX_CALLBACK_NAK_DELAY_SECONDS,
                    )
                    return "nak", _MAX_CALLBACK_NAK_DELAY_SECONDS
                return "nak", delay_seconds
            logger.warning(
                "Callback returned non-positive delayed NAK '%s'; defaulting to immediate NAK",
                action,
            )
            return "nak", None

        logger.warning(
            "Callback returned unsupported action '%s'; defaulting to NAK",
            action,
        )
        return "nak", None

    def _consumer_config(self) -> ConsumerConfig:
        from noetl.core.config import get_worker_settings
        ws = get_worker_settings()
        minimum_ack_wait_seconds = float(ws.command_timeout_seconds) + float(ws.nats_ack_wait_buffer_seconds)
        ack_wait_seconds = self._effective_ack_wait_seconds()
        if ack_wait_seconds > float(ws.nats_ack_wait_seconds):
            logger.warning(
                "Configured NOETL_WORKER_NATS_ACK_WAIT_SECONDS=%.1fs is below minimum %.1fs "
                "(command_timeout + buffer). Using %.1fs.",
                float(ws.nats_ack_wait_seconds),
                minimum_ack_wait_seconds,
                ack_wait_seconds,
            )
        config_kwargs: dict[str, Any] = dict(
            durable_name=self.consumer_name,
            ack_policy="explicit",
            max_deliver=max(1, int(ws.nats_max_deliver)),
            ack_wait=ack_wait_seconds,
            deliver_policy="new",
            replay_policy="instant",
            max_ack_pending=self.max_ack_pending,
        )
        # Only attach filter_subject when set — None / empty leaves
        # the consumer wide open (legacy single-consumer behaviour).
        # See noetl/ai-meta#42 PR-2b.
        if self.filter_subject:
            config_kwargs["filter_subject"] = self.filter_subject
        return ConsumerConfig(**config_kwargs)

    async def _add_or_validate_consumer(self) -> None:
        """Create consumer if missing; tolerate races where another worker creates it first."""
        if not self._js:
            raise RuntimeError("Not connected to NATS")

        try:
            await self._js.add_consumer(
                stream=self.stream_name,
                config=self._consumer_config(),
            )
            logger.info(
                "Created NATS consumer %s (max_ack_pending=%s)",
                self.consumer_name,
                self.max_ack_pending,
            )
            return
        except Exception as add_error:
            try:
                consumer_info = await self._js.consumer_info(self.stream_name, self.consumer_name)
                current_max_ack_pending = getattr(
                    getattr(consumer_info, "config", None),
                    "max_ack_pending",
                    None,
                )
                if (
                    current_max_ack_pending is not None
                    and int(current_max_ack_pending) == int(self.max_ack_pending)
                ):
                    logger.debug(
                        "Consumer %s already exists with expected max_ack_pending=%s",
                        self.consumer_name,
                        self.max_ack_pending,
                    )
                    return
            except Exception:
                pass
            raise RuntimeError(
                f"Failed to create/validate consumer {self.consumer_name}: {add_error}"
            ) from add_error

    async def _recreate_consumer(self, current_max_ack_pending: int) -> None:
        """Recreate durable consumer to enforce max_ack_pending setting."""
        if not self._js:
            raise RuntimeError("Not connected to NATS")

        logger.warning(
            "Consumer %s max_ack_pending=%s differs from configured=%s. Recreating durable consumer.",
            self.consumer_name,
            current_max_ack_pending,
            self.max_ack_pending,
        )

        try:
            await self._js.delete_consumer(self.stream_name, self.consumer_name)
            logger.info("Deleted NATS consumer %s for config reconciliation", self.consumer_name)
        except Exception as delete_error:
            if not self._is_not_found_error(delete_error):
                raise RuntimeError(
                    f"Failed to delete consumer {self.consumer_name} before recreation: {delete_error}"
                ) from delete_error

        await self._add_or_validate_consumer()

    async def _ensure_consumer(self) -> None:
        """Ensure durable consumer exists and matches configured backpressure limits."""
        if not self._js:
            raise RuntimeError("Not connected to NATS")

        try:
            consumer_info = await self._js.consumer_info(self.stream_name, self.consumer_name)
        except Exception as info_error:
            if self._is_not_found_error(info_error):
                await self._add_or_validate_consumer()
                return
            raise RuntimeError(
                f"Failed to get consumer info for {self.consumer_name}: {info_error}"
            ) from info_error

        current_max_ack_pending = getattr(
            getattr(consumer_info, "config", None),
            "max_ack_pending",
            None,
        )
        if current_max_ack_pending is None:
            logger.warning(
                "Consumer %s has no max_ack_pending in config; recreating with configured=%s",
                self.consumer_name,
                self.max_ack_pending,
            )
            await self._recreate_consumer(-1)
            return

        if int(current_max_ack_pending) != int(self.max_ack_pending):
            await self._recreate_consumer(int(current_max_ack_pending))

    async def connect(self):
        """Connect to NATS and setup JetStream."""
        try:
            self._nc = await nats.connect(self.nats_url)
            self._js = self._nc.jetstream()

            logger.debug("Connected to NATS at %s", redact_url_credentials(self.nats_url))

        except Exception as e:
            logger.error(f"Failed to connect to NATS: {e}")
            raise

    async def subscribe(
        self,
        callback: Callable[[dict], Awaitable[Optional[str]]]
    ):
        """
        Subscribe to command notifications.

        Args:
            callback: Async function to call with command notification dict
        """
        if not self._js:
            raise RuntimeError("Not connected to NATS")

        logger.debug(f"Starting subscribe for {self.subject}")

        def create_background_task(coro):
            """Create background task and track it."""
            task = asyncio.create_task(coro)
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            return task

        async def process_message(data: dict, msg):
            """Process message in background - don't block fetch loop."""
            callback_action = "nak"
            callback_nak_delay_seconds: Optional[float] = None
            try:
                action = await self._run_callback_with_message_heartbeat(callback, data, msg)
                callback_action, callback_nak_delay_seconds = self._parse_callback_action(action)
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                logger.warning("Command callback task cancelled; issuing NAK for redelivery")
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
            finally:
                try:
                    if callback_action == "nak":
                        if callback_nak_delay_seconds is not None and callback_nak_delay_seconds > 0:
                            await msg.nak(delay=callback_nak_delay_seconds)
                        else:
                            await msg.nak()
                    elif callback_action == "term":
                        await msg.term()
                    else:
                        await msg.ack()
                    self._record_message_action(callback_action, callback_nak_delay_seconds)
                except Exception as ack_error:
                    logger.warning("Failed to send %s for message: %s", callback_action, ack_error)
                self._inflight_semaphore.release()

        try:
            from noetl.core.runtime.pool_routing import command_stream_subjects
            desired_subjects = command_stream_subjects(self.subject)

            # First ensure stream exists with the widened subjects (see
            # noetl/ai-meta#42 PR-2a — same widening as the publisher
            # side at NATSCommandPublisher.connect).  Subscribers tend
            # to start after a publisher has already created the
            # stream, but this branch handles the cold-start case
            # (e.g. fresh kind cluster where the subscriber wins the
            # race to connect first).
            try:
                info = await self._js.stream_info(self.stream_name)
                current_subjects = list(getattr(info.config, "subjects", None) or [])
                missing = [s for s in desired_subjects if s not in current_subjects]
                if missing:
                    info.config.subjects = current_subjects + missing
                    await self._js.update_stream(config=info.config)
                    logger.info(
                        "Widened %s stream subjects with %s for pool routing (noetl/ai-meta#42)",
                        self.stream_name,
                        missing,
                    )
            except Exception:
                await self._js.add_stream(
                    StreamConfig(
                        name=self.stream_name,
                        subjects=desired_subjects,
                        retention="limits",
                        storage="memory",  # Memory for low latency
                        max_age=3600
                    )
                )
                logger.debug(f"Stream created: {self.stream_name} with subjects={desired_subjects}")

            # Ensure consumer exists and current backpressure settings are applied.
            await self._ensure_consumer()

            # Pull subscription
            self._subscription = await self._js.pull_subscribe(
                self.subject,
                durable=self.consumer_name
            )

            logger.info(f"Subscribed to {self.subject} with consumer {self.consumer_name}")

            # Long-poll fetch loop - returns IMMEDIATELY when message arrives
            while True:
                try:
                    if self._inflight_semaphore.locked():
                        self._throttle_hits += 1
                        if self._throttle_hits % 100 == 0:
                            logger.info(
                                "[NATS-THROTTLE] in-flight limit reached (%s); pausing fetch",
                                self.max_inflight,
                            )

                    await self._inflight_semaphore.acquire()

                    # Long-poll: blocks until message arrives (not polling!)
                    # - timeout=30: max wait time (not polling interval)
                    # - heartbeat=5: keeps connection alive during wait
                    # - Returns IMMEDIATELY when message is available
                    messages = await self._subscription.fetch(
                        batch=1,
                        timeout=self.fetch_timeout,
                        heartbeat=self.fetch_heartbeat
                    )

                    if not messages:
                        self._inflight_semaphore.release()
                        continue

                    for msg in messages:
                        try:
                            data = self._message_decoder(bytes(msg.data))
                            # Process in background and ack/nak based on callback result.
                            create_background_task(process_message(data, msg))

                        except Exception as e:
                            self._inflight_semaphore.release()
                            logger.error(f"Error handling message: {e}")
                            try:
                                await msg.nak()
                                self._record_message_action("nak", None)
                            except:
                                pass

                except asyncio.TimeoutError:
                    self._inflight_semaphore.release()
                    # No messages in 30s, reconnect fetch (normal)
                    continue
                except Exception as e:
                    self._inflight_semaphore.release()
                    logger.error(f"Error fetching messages: {e}")
                    try:
                        await self._recover_fetch_subscription()
                    except Exception as recover_error:
                        logger.warning(
                            "NATS fetch recovery failed for consumer %s: %s",
                            self.consumer_name,
                            recover_error,
                        )
                    await asyncio.sleep(0.1)

        except Exception as e:
            logger.error(f"Subscribe failed: {e}", exc_info=True)
            raise

    async def close(self):
        """Close NATS connection."""
        # Wait for background tasks to complete
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        if self._subscription:
            await self._subscription.unsubscribe()
        if self._nc:
            await self._nc.close()
            logger.info("NATS connection closed")
