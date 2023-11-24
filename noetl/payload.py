import asyncio
from loguru import logger
import uuid
from datetime import datetime
from keyval import KeyVal
from natstream import NatsConnectionPool, NatsConfig


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

    def set_identifier(self, prefix=None, reference=None):
        def prefix_path(key: str):
            return ".".join(filter(None, [prefix, key]))

        self.set_value(prefix_path(key="timestamp"), int(datetime.now().timestamp() * 1000))
        identifier = str(uuid.uuid4())
        reference = reference or identifier
        self.set_value(prefix_path(key="identifier"), identifier)
        self.set_value(prefix_path(key="reference"), reference)

    def set_event_type(self, event_type):
        self.set_value("event_type", event_type)

    def set_command_type(self, command_type):
        self.set_value("command_type", command_type)

    def set_origin_ref(self, origin_ref):
        self.set_value("origin_ref", origin_ref)

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
               origin_ref=None,
               prefix=None,
               reference=None,
               event_type=None,
               command_type=None
               ):
        payload = cls(payload_data, nats_pool=nats_pool)
        payload.set_identifier(prefix=prefix, reference=reference)
        if origin_ref:
            payload.set_origin_ref(origin_ref)
        else:
            payload.set_origin_ref(payload.get_value(f"{prefix}.identifier"))
        if event_type:
            payload.set_event_type(event_type)
        if command_type:
            payload.set_command_type(command_type)
        return payload

    @classmethod
    def kv(cls, payload_data, nats_pool: NatsConnectionPool | NatsConfig = None):
        return cls(payload_data, nats_pool=nats_pool)

    @classmethod
    def workflow_create(cls,
                        workflow_base64,
                        metadata,
                        tokens,
                        event_type,
                        nats_pool: NatsConnectionPool | NatsConfig = None
                        ):
        try:
            name = cls.base64_yaml(workflow_base64).get("metadata").get("name")
            if name:
                return cls.create(
                    payload_data={
                        "workflow_base64": workflow_base64,
                        "metadata": metadata | {
                            "workflow_name": name,
                            "tokens": tokens
                        }
                    },
                    prefix="metadata",
                    event_type=event_type,
                    nats_pool=nats_pool

                )
            else:
                raise ValueError("Workflow name is missing in the YAML.")
        except Exception as e:
            logger.error(f"NoETL API failed to create workflow template: {str(e)}.")
