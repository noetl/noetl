import asyncio
from plugin import Plugin, parse_args, Namespace, logger, NatsConfig, NatsStreamReference
from payload import Payload, PubAck, AppKey, CommandType, Metadata, EventType
from playbook import Playbook

DISPATCHER = AppKey.DISPATCHER
PLAYBOOK_REGISTERED = EventType.PLAYBOOK_REGISTERED
PLAYBOOK_EXECUTION_REGISTERED=EventType.PLAYBOOK_EXECUTION_REGISTERED
PLUGIN_REGISTERED = EventType.PLUGIN_REGISTERED
REVISION_NUMBER = AppKey.REVISION_NUMBER
PLAYBOOK_NAME = AppKey.PLAYBOOK_NAME
METADATA = AppKey.METADATA
PLUGIN_NAME = AppKey.PLUGIN_NAME
IMAGE_URL = AppKey.IMAGE_URL


class Registrar(Plugin):

    async def playbook_register(self, payload: Payload):
        await payload.playbook_put()
        message = payload.encode(keys=[REVISION_NUMBER, PLAYBOOK_NAME, METADATA])
        _ = await payload.event_write(event_type=PLAYBOOK_REGISTERED, plugin=DISPATCHER, message=message)

    async def plugin_register(self, payload: Payload):
        await payload.plugin_put()
        message = payload.encode(keys=[REVISION_NUMBER, PLUGIN_NAME, IMAGE_URL, METADATA])
        _ = await payload.event_write(event_type=PLUGIN_REGISTERED, plugin=DISPATCHER, message=message)

    async def register_playbook_execution_request(self, payload: Payload):
        await payload.snapshot_playbook()
        _ = await payload.event_write(event_type=PLAYBOOK_EXECUTION_REGISTERED, plugin=DISPATCHER)

    async def switch(self, payload: Payload):
        match payload.get_value(Metadata.COMMAND_TYPE):

            case CommandType.REGISTER_PLAYBOOK:
                await self.playbook_register(payload=payload)

            case CommandType.REGISTER_PLUGIN:
                await self.plugin_register(payload=payload)

            case CommandType.REGISTER_PLAYBOOK_EXECUTION:
                await self.register_playbook_execution_request(payload=payload)


if __name__ == "__main__":
    args = parse_args(
        description="NoETL Registrar Plugin",
        default_nats_url="nats://localhost:32222",
        default_nats_pool_size=10,
        default_plugin_name="registrar",
        default_nats_subscription_subject="noetl.command.registrar.>",
        default_nats_subscription_stream="noetl",
        default_nats_subscription_queue="noetl-registrar",
        default_nats_command_prefix="noetl.command",
        default_nats_command_stream="noetl",
        default_nats_event_prefix="noetl.event",
        default_nats_event_stream="noetl",
        default_prom_host="localhost",
        default_prom_port=9091
    )
    registrar_plugin = Registrar()
    registrar_plugin.initialize_nats_pool(NatsConfig(
        nats_url=args.nats_url,
        nats_pool_size=args.nats_pool_size,
    ))
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(registrar_plugin.run(args=args))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.info(f"Dispatcher plugin error: {str(e)}.")
    finally:
        loop.run_until_complete(registrar_plugin.shutdown())
