import os
from argparse import Namespace, ArgumentParser
from functools import partial
from noetl.natstream import NatsStreamReference, NatsPool, NatsConfig, Msg
from aioprometheus import Counter
from aioprometheus.service import Service
from noetl.payload import Payload, logger


class Plugin(NatsPool):
    events_counter: Counter
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

    async def switch(self, payload: Payload):
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
