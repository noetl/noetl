import asyncio
from loguru import logger
import uuid
from dataclasses import dataclass
from datetime import datetime
from keyval import KeyVal
from natstream import NatsConnectionPool, NatsConfig


@dataclass
class PayloadReference:
    """
    The reference structure for payload identifiers in a workflow.

    Attributes:
        origin: The ID of the first event in the workflow, the root or starting point.
        reference: The ID of the predecessor event.
        identifier: The unique ID of the current event or workflow instance.
        timestamp: The Unix timestamp of the payload creation time.

    NATS Stream Key Format:
        The format for NATS streams is '<stream name>.<plugin name>.<origin>.<identifier>',
        where each part represents specific identifiers related to the workflow instance and step.

    Examples of NATS Stream Keys:
        - 'events.dispatcher.12345.abcde' (for an event stream)
        - 'commands.http-handler.12345.bcdef' (for a command stream)
    """

    origin: str = None
    """The origin identifier of the root event in the workflow sequence."""

    reference: str = None
    """The reference identifier of the immediate predecessor event."""

    identifier: str = None
    """The unique identifier of the current event or instance."""

    timestamp: int = None
    """The Unix timestamp of the payload creation time."""

    def __init__(self, origin=None, reference=None):
        self.timestamp = int(datetime.now().timestamp() * 1000)
        self.identifier = str(uuid.uuid4())
        self.reference = reference if reference is not None else self.identifier
        self.origin = origin if origin is not None else self.identifier

    def get_ref(self):
        """
        Returns the reference structure.

        Returns:
            dict: timestamp, identifier, reference, and origin.
        """
        return {
            "timestamp": str(self.timestamp),
            "identifier": self.identifier,
            "reference": self.reference,
            "origin": self.origin
        }


class Payload(KeyVal):
    nats_pool: NatsConnectionPool

    def __init__(self, *args, nats_pool: NatsConnectionPool | NatsConfig = None, **kwargs):
        super().__init__(*args, **kwargs)
        if nats_pool:
            self.set_nats_pool(nats_pool)

    def set_nats_pool(self, nats_pool: NatsConnectionPool | NatsConfig):
        if nats_pool is None:
            self.nats_pool = NatsConnectionPool.get_instance()
        elif isinstance(nats_pool, NatsConfig):
            self.nats_pool = NatsConnectionPool(config=nats_pool)
        elif isinstance(nats_pool, NatsConnectionPool):
            self.nats_pool = nats_pool
        else:
            raise TypeError("nats_pool must be type of NatsConnectionPool or NatsConfig")

    def set_ref(self, reference: PayloadReference):
        self.set_value("metadata.ref", reference.get_ref())

    def get_subject_ref(self):
        origin = self.get_value("metadata.ref.origin")
        identifier = self.get_value("metadata.ref.identifier")
        return f"{origin}.{identifier}"

    def get_ref(self):
        return self.get_value("metadata.ref")

    def set_event_type(self, event_type):
        self.set_value("metadata.event_type", event_type)

    def set_command_type(self, command_type):
        self.set_value("metadata.command_type", command_type)

    async def nats_read(self, subject: str, cb):
        async with self.nats_pool.connection() as nc:
            await nc.subscribe(subject, cb=cb)
            while True:
                await asyncio.sleep(1)

    async def nats_write(self, subject: str, message: bytes):
        async with self.nats_pool.connection() as nc:
            return await nc.publish(subject, message)

    async def command_write(self, subject: str, message: bytes):
        return await self.nats_write(f"command.{subject}", message)

    async def event_write(self, subject: str, message: bytes):
        return await self.nats_write(f"event.{subject}", message)

    async def workflow_bucket_create(self):
        await self.nats_pool.bucket_create(bucket_name="workflows")

    async def workflow_bucket_delete(self):
        await self.nats_pool.bucket_delete(bucket_name="workflows")

    async def workflow_put(self, key: str, value: bytes):
        return await self.nats_pool.kv_put(bucket_name="workflows", key=key, value=value)

    async def workflow_get(self, key: str):
        return await self.nats_pool.kv_get(bucket_name="workflows", key=key)

    async def workflow_delete(self, key: str):
        await self.nats_pool.kv_delete(bucket_name="workflows", key=key)

    async def plugin_bucket_create(self):
        await self.nats_pool.bucket_create(bucket_name="plugins")

    async def plugin_bucket_delete(self):
        await self.nats_pool.bucket_delete(bucket_name="plugins")

    async def plugin_put(self, key: str, value: bytes):
        return await self.nats_pool.kv_put(bucket_name="plugins", key=key, value=value)

    async def plugin_get(self, key: str):
        return await self.nats_pool.kv_get(bucket_name="plugins", key=key)

    async def plugin_delete(self, key: str):
        await self.nats_pool.kv_delete(bucket_name="plugins", key=key)

    @classmethod
    def create(cls,
               payload_data,
               nats_pool: NatsConnectionPool | NatsConfig = None,
               origin=None,
               reference=None,
               event_type=None,
               command_type=None
               ):
        payload_reference = PayloadReference(origin=origin, reference=reference)
        payload = cls(payload_data, nats_pool=nats_pool)
        payload.set_ref(reference=payload_reference)
        if event_type:
            payload.set_event_type(event_type)
        if command_type:
            payload.set_command_type(command_type)
        return payload

    @classmethod
    def kv(cls, payload_data, nats_pool: NatsConnectionPool | NatsConfig = None):
        return cls(payload_data, nats_pool=nats_pool)
