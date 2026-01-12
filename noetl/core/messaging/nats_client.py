"""
NATS JetStream client for NoETL V2 command notifications.

Architecture:
- Server publishes lightweight command notifications to NATS subject
- Workers subscribe and fetch full command details from queue API
- Workers execute and emit events back to server
"""

import asyncio
import logging
from typing import Optional, Callable, Awaitable
import nats
from nats.js import JetStreamContext
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
                    storage="file"
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
        
        async def message_handler(msg):
            """Handle incoming NATS message."""
            try:
                import json
                data = json.loads(msg.data.decode())
                
                logger.debug(f"Received command notification: {data}")
                
                # Call the callback FIRST (command claiming is atomic via database)
                await callback(data)
                
                # Acknowledge message AFTER successful processing
                # This ensures exactly-once delivery: if callback fails, message is redelivered
                await msg.ack()
                logger.debug(f"Acknowledged message for command_id={data.get('command_id')}")
                
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
                # NAK the message to allow redelivery (up to max_deliver limit)
                # This ensures another worker can try processing it
                try:
                    await msg.nak()
                    logger.debug(f"NAK'd message for command_id={data.get('command_id')} due to error")
                except Exception as nak_err:
                    logger.error(f"Failed to NAK message: {nak_err}")
        
        try:
            # First ensure stream exists
            try:
                logger.debug(f"Checking if stream {self.stream_name} exists...")
                await self._js.stream_info(self.stream_name)
                logger.debug("Stream exists")
            except Exception as stream_err:
                logger.debug(f"Creating stream {self.stream_name} | reason: {stream_err}")
                # Create stream if it doesn't exist
                from nats.js.api import StreamConfig
                await self._js.add_stream(
                    StreamConfig(
                        name=self.stream_name,
                        subjects=[self.subject],
                        retention="limits",
                        max_age=3600  # 1 hour
                    )
                )
                logger.debug(f"Stream created: {self.stream_name}")
            
            # Create pull consumer if it doesn't exist
            try:
                logger.debug(f"Checking consumer {self.consumer_name}...")
                await self._js.consumer_info(self.stream_name, self.consumer_name)
                logger.debug("Consumer exists")
            except Exception as consumer_err:
                logger.debug(f"Creating consumer {self.consumer_name} | reason: {consumer_err}")
                await self._js.add_consumer(
                    stream=self.stream_name,
                    config=nats.js.api.ConsumerConfig(
                        durable_name=self.consumer_name,
                        ack_policy="explicit",
                        max_deliver=3,  # Allow 3 attempts in case of transient failures
                        ack_wait=60,  # 60 seconds - reasonable time for worker to process and ack
                        deliver_policy="all",  # Deliver all available messages
                        replay_policy="instant"  # Deliver messages as fast as possible
                    )
                )
                logger.debug(f"Consumer created: {self.consumer_name}")
            
            # Subscribe with pull consumer
            logger.debug("Creating pull subscription...")
            self._subscription = await self._js.pull_subscribe(
                self.subject,
                durable=self.consumer_name
            )
            
            logger.debug(f"Subscribed to {self.subject} with consumer {self.consumer_name}")
            
            # Start message fetch loop
            logger.debug("Starting fetch loop...")
            while True:
                try:
                    # Fetch with 1-second timeout for faster command pickup
                    # This allows workers to respond to new commands within 1s
                    messages = await self._subscription.fetch(batch=1, timeout=1)
                except asyncio.TimeoutError:
                    # GPT do net add any logs to this line!!!
                    continue
                except Exception as e:
                    logger.error(f"Error fetching nats messages: {e}")
                    await asyncio.sleep(1)

                try:
                    for msg in messages:
                        await message_handler(msg)
                except Exception as e:
                    logger.exception(f"Error fetching nats messages: {e}")
                    await asyncio.sleep(1)
            
        except Exception as e:
            logger.error(f"Subscribe failed: {e}", exc_info=True)
            import traceback
            traceback.print_exc()
            raise
    
    async def close(self):
        """Close NATS connection."""
        if self._subscription:
            await self._subscription.unsubscribe()
        if self._nc:
            await self._nc.close()
            logger.info("NATS connection closed")
