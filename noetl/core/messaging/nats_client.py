"""
NATS JetStream client for NoETL V2 command notifications.

Architecture:
- Server publishes lightweight command notifications to NATS subject
- Workers subscribe and fetch full command details from queue API
- Workers execute and emit events back to server

Performance tuning:
- Ack IMMEDIATELY on message receipt (don't wait for processing)
- Process messages in background tasks (don't block fetch loop)
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
    - Ack immediately on receipt (don't wait for processing)
    - Process in background task (don't block fetch loop)
    - Exactly-once handled by database advisory locks
    """

    def __init__(
        self,
        nats_url: Optional[str] = None,
        subject: Optional[str] = None,
        consumer_name: Optional[str] = None,
        stream_name: Optional[str] = None
    ):
        from noetl.core.config import get_worker_settings
        ws = get_worker_settings()
        self.nats_url = nats_url or ws.nats_url
        self.subject = subject or ws.nats_subject
        self.consumer_name = consumer_name or ws.nats_consumer
        self.stream_name = stream_name or ws.nats_stream
        self._nc: Optional[NATSClient] = None
        self._js: Optional[JetStreamContext] = None
        self._subscription = None
        self._background_tasks: set = set()

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
        callback: Callable[[dict], Awaitable[None]]
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

        async def process_message(data: dict):
            """Process message in background - don't block fetch loop."""
            try:
                await callback(data)
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)

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

            # Create/update consumer with optimized settings
            try:
                await self._js.consumer_info(self.stream_name, self.consumer_name)
            except Exception:
                await self._js.add_consumer(
                    stream=self.stream_name,
                    config=ConsumerConfig(
                        durable_name=self.consumer_name,
                        ack_policy="explicit",
                        max_deliver=3,
                        ack_wait=30,  # Reduced from 60s
                        deliver_policy="new",  # Only new messages, not old ones
                        replay_policy="instant",
                        max_ack_pending=1000,  # Allow many pending
                    )
                )
                logger.debug(f"Consumer created: {self.consumer_name}")

            # Pull subscription
            self._subscription = await self._js.pull_subscribe(
                self.subject,
                durable=self.consumer_name
            )

            logger.info(f"Subscribed to {self.subject} with consumer {self.consumer_name}")

            # Long-poll fetch loop - returns IMMEDIATELY when message arrives
            while True:
                try:
                    # Long-poll: blocks until message arrives (not polling!)
                    # - timeout=30: max wait time (not polling interval)
                    # - heartbeat=5: keeps connection alive during wait
                    # - Returns IMMEDIATELY when message is available
                    messages = await self._subscription.fetch(
                        batch=1,
                        timeout=30,
                        heartbeat=5
                    )

                    for msg in messages:
                        try:
                            import json
                            data = json.loads(msg.data.decode())

                            # ACK IMMEDIATELY - don't wait for processing
                            # Database advisory lock handles exactly-once
                            await msg.ack()

                            # Process in background - don't block fetch loop
                            create_background_task(process_message(data))

                        except Exception as e:
                            logger.error(f"Error handling message: {e}")
                            try:
                                await msg.nak()
                            except:
                                pass

                except asyncio.TimeoutError:
                    # No messages in 30s, reconnect fetch (normal)
                    continue
                except Exception as e:
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
