"""
NATS JetStream client for NoETL V2 command notifications.

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
from typing import Optional, Callable, Awaitable
import nats
from nats.js import JetStreamContext
from nats.js.api import StreamConfig, ConsumerConfig
from nats.aio.client import Client as NATSClient

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


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

    async def connect(self):
        """Connect to NATS and setup JetStream."""
        try:
            self._nc = await nats.connect(self.nats_url)
            self._js = self._nc.jetstream()

            # Ensure stream exists
            try:
                await self._js.stream_info(self.stream_name)
                logger.debug(f"Using existing {self.stream_name} stream")
            except Exception:
                # Create stream if it doesn't exist
                await self._js.add_stream(
                    name=self.stream_name,
                    subjects=[self.subject],
                    max_age=3600,  # 1 hour retention
                    storage="memory"  # Memory for low latency
                )
                logger.info(f"Created stream {self.stream_name} | connected to NATS at {self.nats_url}")

        except Exception as e:
            logger.error(f"Failed to connect to NATS: {e}")
            raise

    async def publish_command(
        self,
        execution_id: int,
        event_id: int,
        command_id: str,
        step: str,
        server_url: str
    ):
        """
        Publish command notification to NATS.

        Event-driven approach:
        - event_id: Points to command.issued event with full command details
        - command_id: Unique identifier for atomic claiming
        - Workers claim by emitting command.claimed event (idempotent)
        """
        if not self._js:
            raise RuntimeError("Not connected to NATS")

        message = {
            "execution_id": execution_id,
            "event_id": event_id,
            "command_id": command_id,
            "step": step,
            "server_url": server_url
        }

        try:
            import json
            await self._js.publish(
                self.subject,
                json.dumps(message).encode()
            )
            logger.debug(f"Published command notification: event_id={event_id} command_id={command_id}")

        except Exception as e:
            logger.error(f"Failed to publish command: {e}")
            raise

    async def close(self):
        """Close NATS connection."""
        if self._nc:
            await self._nc.close()
            logger.info("NATS connection closed")


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
    ):
        from noetl.core.config import get_worker_settings
        ws = get_worker_settings()
        self.nats_url = nats_url or ws.nats_url
        self.subject = subject or ws.nats_subject
        self.consumer_name = consumer_name or ws.nats_consumer
        self.stream_name = stream_name or ws.nats_stream
        self.max_inflight = max(1, int(max_inflight or ws.max_inflight_commands))
        self.max_ack_pending = max(1, int(max_ack_pending or ws.nats_max_ack_pending))
        self.fetch_timeout = float(fetch_timeout if fetch_timeout is not None else ws.nats_fetch_timeout_seconds)
        self.fetch_heartbeat = float(fetch_heartbeat if fetch_heartbeat is not None else ws.nats_fetch_heartbeat_seconds)
        self.callback_timeout_seconds = float(
            callback_timeout_seconds
            if callback_timeout_seconds is not None
            else ws.command_timeout_seconds
        )
        self._nc: Optional[NATSClient] = None
        self._js: Optional[JetStreamContext] = None
        self._subscription = None
        self._background_tasks: set = set()
        self._inflight_semaphore = asyncio.Semaphore(self.max_inflight)
        self._throttle_hits = 0

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

    def _consumer_config(self) -> ConsumerConfig:
        from noetl.core.config import get_worker_settings
        ws = get_worker_settings()
        return ConsumerConfig(
            durable_name=self.consumer_name,
            ack_policy="explicit",
            max_deliver=max(1, int(ws.nats_max_deliver)),
            ack_wait=30,
            deliver_policy="new",
            replay_policy="instant",
            max_ack_pending=self.max_ack_pending,
        )

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

            logger.debug(f"Connected to NATS at {self.nats_url}")

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
            try:
                action = await asyncio.wait_for(
                    callback(data),
                    timeout=self.callback_timeout_seconds,
                )
                if isinstance(action, str):
                    normalized = action.strip().lower()
                    if normalized in {"ack", "nak", "term"}:
                        callback_action = normalized
                    else:
                        logger.warning(
                            "Callback returned unsupported action '%s'; defaulting to NAK",
                            action,
                        )
                else:
                    logger.warning(
                        "Callback returned non-string action (%s); defaulting to NAK",
                        type(action).__name__,
                    )
            except asyncio.TimeoutError:
                logger.error(
                    "Command callback timed out after %.1fs; issuing NAK for redelivery",
                    self.callback_timeout_seconds,
                )
            except asyncio.CancelledError:
                logger.warning("Command callback task cancelled; issuing NAK for redelivery")
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
            finally:
                try:
                    if callback_action == "nak":
                        await msg.nak()
                    elif callback_action == "term":
                        await msg.term()
                    else:
                        await msg.ack()
                except Exception as ack_error:
                    logger.warning("Failed to send %s for message: %s", callback_action, ack_error)
                self._inflight_semaphore.release()

        try:
            # First ensure stream exists
            try:
                await self._js.stream_info(self.stream_name)
            except Exception:
                await self._js.add_stream(
                    StreamConfig(
                        name=self.stream_name,
                        subjects=[self.subject],
                        retention="limits",
                        storage="memory",  # Memory for low latency
                        max_age=3600
                    )
                )
                logger.debug(f"Stream created: {self.stream_name}")

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
                            import json
                            data = json.loads(msg.data.decode())
                            # Process in background and ack/nak based on callback result.
                            create_background_task(process_message(data, msg))

                        except Exception as e:
                            self._inflight_semaphore.release()
                            logger.error(f"Error handling message: {e}")
                            try:
                                await msg.nak()
                            except:
                                pass

                except asyncio.TimeoutError:
                    self._inflight_semaphore.release()
                    # No messages in 30s, reconnect fetch (normal)
                    continue
                except Exception as e:
                    self._inflight_semaphore.release()
                    logger.error(f"Error fetching messages: {e}")
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
