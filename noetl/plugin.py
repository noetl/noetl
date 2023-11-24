import argparse
import os
from dataclasses import dataclass
from natstream import NatsStreamReference
from aioprometheus import Counter
from aioprometheus.service import Service
from loguru import logger
from payload import Payload


@dataclass
class Plugin(Payload):
    events_counter: Counter

    async def process_stream(self, msg):
        payload = Payload.decode(msg.data)
        nats_reference = NatsStreamReference(
            nats_msg_metadata=msg.metadata,
            nats_msg_subject=msg.subject,
            nats_msg_headers=msg.headers
        )
        logger.debug(f"payload: {payload}, nats_reference: {nats_reference}")
        _ = await self.switch(payload=payload, nats_reference=nats_reference)

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
