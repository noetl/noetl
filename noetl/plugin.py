import argparse
import os
from natstream import NatsStreamReference, NatsPool
from aioprometheus import Counter
from aioprometheus.service import Service
from loguru import logger
from payload import Payload, PayloadReference


class Plugin(NatsPool):
    events_counter: Counter

    async def write_command_payload(self,payload_orig: Payload, payload_data: dict, subject: str):
        await self.write_payload(
            payload_orig=payload_orig,
            payload_data=payload_data,
            subject=subject)

    async def write_event_payload(self,payload_orig: Payload, payload_data: dict, subject: str):
        await self.write_payload(
            payload_orig=payload_orig,
            payload_data=payload_data,
            subject=subject,
            event=True)

    async def write_payload(self, payload_orig: Payload, payload_data: dict, subject: str, event: bool = False):
        payload_reference: PayloadReference = PayloadReference(**payload_orig.get_payload_reference())
        payload: Payload = Payload.create(
            payload_data=payload_data,
            origin=payload_reference.origin,
            reference=payload_reference.identifier,
            nats_pool=await self.get_nats_pool()
        )
        if event is True:
            ack = await payload.event_write(
                subject=f"{subject}.{payload.get_origin_ref()}",
                message=payload.encode()
            )
        else:
            ack = await payload.command_write(
                subject=f"{subject}.{payload.get_origin_ref()}",
                message=payload.encode()
            )
        logger.debug(ack)

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
        raise NotImplementedError("Plugin subclass must implement switch method")

    async def run(self, args, plugin_name, stream="commands"):
        service = Service()
        await service.start(addr=args.prom_host, port=args.prom_port)
        logger.info(f"Serving prometheus metrics on: {service.metrics_url}")
        subject_prefix = "noetl.command" if stream == "commands" else "noetl.event"
        logger.info(f"{stream} -> {subject_prefix}.{plugin_name}.> ")
        _ = await self.nats_read(f"{subject_prefix}.{plugin_name}.>", stream=stream, cb=self.process_stream)

    async def shutdown(self):
        if self.nats_pool:
            await self.nats_pool.close_pool()


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
