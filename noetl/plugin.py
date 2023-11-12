import argparse
import os
import asyncio
import socket
from dataclasses import dataclass
from natstream import NatsConnectionPool, NatsConfig, NatsStreamReference
from aioprometheus import Counter
from aioprometheus.service import Service
from loguru import logger
from payload import Payload



@dataclass
class Plugin:
    events_counter: Counter
    nats_pool: NatsConnectionPool
    records: list[Payload] | None = None

    @classmethod
    def create(cls, nats_config: NatsConfig):
        return cls(
            events_counter=Counter(
                f"{cls.__name__}_events_total",
                "Number of events.",
                const_labels={"host": socket.gethostname()}
            ),
            nats_pool=NatsConnectionPool(config=nats_config)
        )

    async def nats_read(self, subject: str, cb):
        async with self.nats_pool.connection() as nc:
            await nc.subscribe(subject, cb=cb)
            while True:
                await asyncio.sleep(1)

    async def nats_write(self, subject: str, message: bytes):
        async with self.nats_pool.connection() as nc:
            await nc.publish(subject, message)

    async def command_write(self, subject: str, message: bytes):
        await self.nats_write(f"command.{subject}", message)

    async def event_write(self, subject: str, message: bytes):
        await self.nats_write(f"event.{subject}", message)

    async def process_stream(self, msg):
        payload = Payload.decode(msg.data)
        nats_reference=NatsStreamReference(
            nats_msg_metadata=msg.metadata,
            nats_msg_subject=msg.subject,
            nats_msg_headers=msg.headers
        )
        _ = await self.switch(payload=payload, nats_reference=nats_reference)
        logger.debug(payload)

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
        await self.nats_pool.kv_put(bucket_name="plugins", key=key, value=value)

    async def plugin_get(self, key: str):
        await self.nats_pool.kv_get(bucket_name="plugins", key=key)

    async def plugin_delete(self, key: str):
        await self.nats_pool.kv_delete(bucket_name="plugins", key=key)

    async def switch(self,
                     payload: Payload,
                     nats_reference: NatsStreamReference
                     ):
        raise NotImplementedError("Subclasses must implement this method")

    async def run(self, args, subject_prefix):
        service = Service()
        await service.start(addr=args.prom_host, port=args.prom_port)
        logger.info(f"Serving prometheus metrics on: {service.metrics_url}")
        _ = await self.nats_read(f"{subject_prefix}.>", self.process_stream)


def parse_args(description, default_nats_url, default_nats_pool_size, default_prom_host, default_prom_port):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--nats_url",
                        default=os.getenv('NATS_URL', default_nats_url), help="NATS server URL")
    parser.add_argument("--nats_pool_size", type=int,
                        default=int(os.getenv('NATS_POLL_SIZE', default_nats_pool_size)), help="NATS pool size")
    parser.add_argument("--prom_host",
                        default=os.getenv('PROM_HOST', default_prom_host), help="Prometheus host")
    parser.add_argument("--prom_port", type=int,
                        default=int(os.getenv('PROM_PORT', default_prom_port)), help="Prometheus port")
    return parser.parse_args()
