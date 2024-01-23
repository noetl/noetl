import os
from abc import ABC, abstractmethod
from argparse import Namespace, ArgumentParser
from functools import partial
from noetl.natstream import NatsStreamReference, NatsPool, NatsConfig, Msg
from aioprometheus import Counter
from aioprometheus.service import Service
from noetl.payload import Payload, logger


class Plugin(NatsPool, ABC):
    events_counter: Counter

    async def subscribe(self, args):
        """
        Default NATS subscription. Can be overridden for custom subscription if needed.
        """
        logger.info(f"Nats stream: {args.nats_subscription_stream}")
        logger.info(f"Nats subject: {args.nats_subscription_subject}")
        cb = partial(self.process_stream, args)
        await self.nats_read(
            subject=args.nats_subscription_subject,
            stream=args.nats_subscription_stream,
            queue=args.nats_subscription_queue,
            cb=cb)

    @abstractmethod
    async def switch(self, payload: Payload):
        """
        Plugin Subclass must implement switch method.
        """
        pass

    async def process_stream(self,
                             args: Namespace,
                             msg: Msg):
        payload = Payload.decode(msg.data)
        payload.set_nats_pool(nats_pool=self.nats_pool)
        payload.info = vars(args)
        payload.nats_reference = NatsStreamReference(
            nats_msg_metadata=msg.metadata,
            nats_msg_subject=msg.subject,
            nats_msg_headers=msg.headers,
            nats_msg_reply=msg.reply
        )
        logger.debug(f"payload: {payload}")
        _ = await self.switch(payload=payload)

    async def run(self, args):
        """
        Default run using NATS. Can be overridden by subclasses.
        """
        service = Service()
        await service.start(addr=args.prom_host, port=args.prom_port)
        logger.info(f"Serving prometheus metrics on: {service.metrics_url}")
        await self.subscribe(args)

    async def shutdown(self):
        if self.nats_pool:
            await self.nats_pool.close_pool()


def parse_args(description, **kwargs):
    parser = ArgumentParser(description=description)
    args = Namespace()
    for arg, value in kwargs.items():
        env_var, default, help_text = value
        env_value = os.getenv(env_var.upper())
        value = env_value if env_value else default
        setattr(args, arg, value)
        parser.add_argument(f"--{arg}", default=value, help=help_text)
    return args
