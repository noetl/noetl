import os
from argparse import Namespace, ArgumentParser
from functools import partial
from natstream import NatsStreamReference, NatsPool, NatsConfig, Msg
from aioprometheus import Counter
from aioprometheus.service import Service
from loguru import logger
from payload import Payload, PayloadType, AppKey


class Plugin(NatsPool):
    events_counter: Counter

    async def publish_command(self,
                              payload_orig: Payload,
                              payload_data: dict,
                              subject_prefix: str,
                              stream: str):
        await self.write_payload(
            payload_orig=payload_orig,
            payload_data=payload_data,
            subject_prefix=subject_prefix,
            stream=stream,
            payload_type=PayloadType.COMMAND)

    async def publish_event(self,
                            payload_orig: Payload,
                            payload_data: dict,
                            subject_prefix: str,
                            stream: str):
        await self.write_payload(
            payload_orig=payload_orig,
            payload_data=payload_data,
            subject_prefix=subject_prefix,
            stream=stream,
            payload_type=PayloadType.EVENT)

    async def write_payload(self,
                            payload_orig: Payload,
                            payload_data: dict,
                            subject_prefix: str,
                            stream: str,
                            payload_type: PayloadType):
        payload: Payload = Payload.create(
            payload_data=payload_data,
            origin_id=payload_orig.get_origin_id(),
            current_id=payload_orig.get_current_id(),
            nats_pool=await self.get_nats_pool())
        match payload_type:
            case PayloadType.EVENT:
                ack = await payload.event_write(
                    subject=f"{subject_prefix}.{payload.get_origin_id()}",
                    stream=stream,
                    message=payload.encode()
                )
            case PayloadType.COMMAND:
                ack = await payload.command_write(
                    subject=f"{subject_prefix}.{payload.get_origin_id()}",
                    stream=stream,
                    message=payload.encode()
                )
            case _:
                ack = None
        logger.debug(ack)

    async def process_stream(self,
                             args: Namespace,
                             msg: Msg):
        payload = Payload.decode(msg.data)
        payload.set_nats_pool(nats_pool=self.nats_pool)
        nats_reference = NatsStreamReference(
            nats_msg_metadata=msg.metadata,
            nats_msg_subject=msg.subject,
            nats_msg_headers=msg.headers,
            nats_msg_reply=msg.reply
        )
        logger.debug(f"payload: {payload}, nats_reference: {nats_reference}")
        _ = await self.switch(payload=payload, nats_reference=nats_reference, args=args)

    async def switch(self,
                     payload: Payload,
                     nats_reference: NatsStreamReference,
                     args: Namespace):
        raise NotImplementedError("Plugin subclass must implement switch method")

    async def run(self, args):
        service = Service()
        await service.start(addr=args.prom_host, port=args.prom_port)
        logger.info(f"Serving prometheus metrics on: {service.metrics_url}")
        logger.info(f"Nats stream:{args.nats_subscription_stream}")
        logger.info(f"Nats subject: {args.nats_subscription_subject}")
        cb = partial(self.process_stream, args)
        _ = await self.nats_read(
            subject=args.nats_subscription_subject,
            stream=args.nats_subscription_stream,
            queue=args.nats_subscription_queue,
            cb=cb)

    async def shutdown(self):
        if self.nats_pool:
            await self.nats_pool.close_pool()


def parse_args(
        description,
        default_plugin_name,
        default_nats_url,
        default_nats_pool_size,
        default_nats_subscription_subject,
        default_nats_subscription_stream,
        default_nats_subscription_queue,
        default_nats_command_prefix,
        default_nats_command_stream,
        default_nats_event_prefix,
        default_nats_event_stream,
        default_prom_host,
        default_prom_port):
    parser = ArgumentParser(description=description)
    parser.add_argument("--plugin_name",
                        default=os.getenv('PLUGIN_NAME', default_plugin_name), help="Plugin name")
    parser.add_argument("--nats_url",
                        default=os.getenv('NATS_URL', default_nats_url), help="NATS server URL")
    parser.add_argument("--nats_pool_size", type=int,
                        default=int(os.getenv('NATS_POLL_SIZE', default_nats_pool_size)), help="NATS pool size")
    parser.add_argument("--nats_subscription_subject",
                        default=os.getenv('NATS_SUBSCRIPTION_SUBJECT', default_nats_subscription_subject),
                        help="NATS subject for subscription")
    parser.add_argument("--nats_subscription_stream",
                        default=os.getenv('NATS_SUBSCRIPTION_STREAM', default_nats_subscription_stream),
                        help="NATS subscription stream")
    parser.add_argument("--nats_subscription_queue",
                        default=os.getenv('NATS_SUBSCRIPTION_QUEUE', default_nats_subscription_queue),
                        help="NATS JetStream subscription group queue")
    parser.add_argument("--nats_command_prefix",
                        default=os.getenv('NATS_COMMAND_PREFIX', default_nats_command_prefix),
                        help="NATS subject prefix for commands")
    parser.add_argument("--nats_command_stream",
                        default=os.getenv('NATS_COMMAND_STREAM', default_nats_command_stream),
                        help="NATS JetStream name for commands")
    parser.add_argument("--nats_event_prefix",
                        default=os.getenv('NATS_EVENT_PREFIX', default_nats_event_prefix),
                        help="NATS subject prefix for events")
    parser.add_argument("--nats_event_stream",
                        default=os.getenv('NATS_EVENT_STREAM', default_nats_event_stream),
                        help="NATS JetStream name for events")
    parser.add_argument("--prom_host",
                        default=os.getenv('PROM_HOST', default_prom_host), help="Prometheus host")
    parser.add_argument("--prom_port", type=int,
                        default=int(os.getenv('PROM_PORT', default_prom_port)), help="Prometheus port")
    return parser.parse_args()
