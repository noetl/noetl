import argparse
import asyncio
import socket
from dataclasses import dataclass
from natstream import NatsConnectionPool, NatsConfig
from aioprometheus import Counter
from aioprometheus.service import Service
from record import Record
from loguru import logger


@dataclass
class NoETLHandler:
    events_counter: Counter
    nats_pool: NatsConnectionPool
    records: list[Record] | None = None

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

    async def process_stream(self, msg):
        input_data = Record.deserialize(msg.data)
        _ = await self.switch(input_data)
        logger.debug(input_data)

    async def switch(self, data):
        raise NotImplementedError("Subclasses must implement this method")

    async def run(self, args, subject_prefix):
        service = Service()
        await service.start(addr=args.prom_host, port=args.prom_port)
        logger.info(f"Serving prometheus metrics on: {service.metrics_url}")
        _ = await self.nats_read(f"{subject_prefix}.>", self.process_stream)


def parse_args(description, default_nats_url, default_nats_pool_size, default_prom_host, default_prom_port):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--nats_url", default=default_nats_url, help="NATS server URL")
    parser.add_argument("--nats_pool_size", type=int, default=default_nats_pool_size, help="NATS pool size")
    parser.add_argument("--prom_host", default=default_prom_host, help="Prometheus host")
    parser.add_argument("--prom_port", type=int, default=default_prom_port, help="Prometheus port")
    return parser.parse_args()
