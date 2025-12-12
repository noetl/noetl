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
        nats_url: str = "nats://noetl:noetl@localhost:30422",
        subject: str = "noetl.commands"
    ):
        self.nats_url = nats_url
        self.subject = subject
        self._nc: Optional[NATSClient] = None
        self._js: Optional[JetStreamContext] = None
    
    async def connect(self):
        """Connect to NATS and setup JetStream."""
        try:
            self._nc = await nats.connect(self.nats_url)
            self._js = self._nc.jetstream()
            
            # Ensure stream exists
            try:
                await self._js.stream_info("NOETL_COMMANDS")
                logger.info("Using existing NOETL_COMMANDS stream")
            except Exception:
                # Create stream if it doesn't exist
                await self._js.add_stream(
                    name="NOETL_COMMANDS",
                    subjects=["noetl.commands"],
                    max_age=3600,  # 1 hour retention
                    storage="file"
                )
                logger.info("Created NOETL_COMMANDS stream")
            
            logger.info(f"Connected to NATS at {self.nats_url}")
            
        except Exception as e:
            logger.error(f"Failed to connect to NATS: {e}")
            raise
    
    async def publish_command(
        self,
        execution_id: int,
        queue_id: int,
        step: str,
        server_url: str
    ):
        """
        Publish command notification to NATS.
        
        Workers will receive this and fetch full command from queue API.
        """
        if not self._js:
            raise RuntimeError("Not connected to NATS")
        
        message = {
            "execution_id": execution_id,
            "queue_id": queue_id,
            "step": step,
            "server_url": server_url
        }
        
        try:
            import json
            await self._js.publish(
                self.subject,
                json.dumps(message).encode()
            )
            logger.debug(f"Published command notification: {message}")
            
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
        nats_url: str = "nats://noetl:noetl@localhost:30422",
        subject: str = "noetl.commands",
        consumer_name: Optional[str] = None
    ):
        self.nats_url = nats_url
        self.subject = subject
        self.consumer_name = consumer_name or "noetl-worker-pool"
        self._nc: Optional[NATSClient] = None
        self._js: Optional[JetStreamContext] = None
        self._subscription = None
    
    async def connect(self):
        """Connect to NATS and setup JetStream."""
        try:
            self._nc = await nats.connect(self.nats_url)
            self._js = self._nc.jetstream()
            
            logger.info(f"Connected to NATS at {self.nats_url}")
            
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
        
        print(f"Starting subscribe for {self.subject}", flush=True)
        
        async def message_handler(msg):
            """Handle incoming NATS message."""
            try:
                import json
                data = json.loads(msg.data.decode())
                
                logger.debug(f"Received command notification: {data}")
                
                # Call the callback
                await callback(data)
                
                # Acknowledge message
                await msg.ack()
                
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
                # NAK to requeue
                await msg.nak()
        
        try:
            # First ensure stream exists
            try:
                print("Checking if stream NOETL_COMMANDS exists...", flush=True)
                await self._js.stream_info("NOETL_COMMANDS")
                print("Stream exists", flush=True)
            except Exception as stream_err:
                print(f"Stream check error: {stream_err}", flush=True)
                print("Creating stream NOETL_COMMANDS...", flush=True)
                # Create stream if it doesn't exist
                from nats.js.api import StreamConfig
                await self._js.add_stream(
                    StreamConfig(
                        name="NOETL_COMMANDS",
                        subjects=["noetl.commands"],
                        retention="limits",
                        max_age=3600  # 1 hour
                    )
                )
                print("Stream created", flush=True)
                logger.info("Created stream: NOETL_COMMANDS")
            
            # Create pull consumer if it doesn't exist
            try:
                print(f"Checking consumer {self.consumer_name}...", flush=True)
                await self._js.consumer_info("NOETL_COMMANDS", self.consumer_name)
                print("Consumer exists", flush=True)
            except Exception as consumer_err:
                print(f"Consumer check error: {consumer_err}", flush=True)
                print(f"Creating consumer {self.consumer_name}...", flush=True)
                await self._js.add_consumer(
                    stream="NOETL_COMMANDS",
                    config=nats.js.api.ConsumerConfig(
                        durable_name=self.consumer_name,
                        ack_policy="explicit",
                        max_deliver=3,
                        ack_wait=30  # 30 seconds to process and ack
                    )
                )
                print("Consumer created", flush=True)
                logger.info(f"Created consumer: {self.consumer_name}")
            
            # Subscribe with pull consumer
            print("Creating pull subscription...", flush=True)
            self._subscription = await self._js.pull_subscribe(
                self.subject,
                durable=self.consumer_name
            )
            
            print(f"Subscribed to {self.subject}", flush=True)
            logger.info(f"Subscribed to {self.subject} with consumer {self.consumer_name}")
            
            # Start message fetch loop
            print("Starting fetch loop...", flush=True)
            while True:
                try:
                    messages = await self._subscription.fetch(batch=1, timeout=5)
                    for msg in messages:
                        await message_handler(msg)
                except asyncio.TimeoutError:
                    # No messages, continue polling
                    print(".", end="", flush=True)  # Heartbeat
                    continue
                except Exception as e:
                    print(f"\nFetch error: {e}", flush=True)
                    logger.error(f"Error fetching messages: {e}")
                    await asyncio.sleep(1)
            
        except Exception as e:
            print(f"Subscribe failed: {e}", flush=True)
            logger.error(f"Failed to subscribe: {e}", exc_info=True)
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
