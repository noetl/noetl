import asyncio
from plugin import Plugin, parse_args, logger, NatsConfig
from payload import Payload, AppKey, CommandType, Metadata, RawStreamMsg
from playbook import Playbook

REGISTER_PLAYBOOK = CommandType.REGISTER_PLAYBOOK
REGISTER_PLUGIN = CommandType.REGISTER_PLUGIN
REGISTER_PLAYBOOK_EXECUTION = CommandType.REGISTER_PLAYBOOK_EXECUTION
REGISTRAR = AppKey.REGISTRAR


class Dispatcher(Plugin):

    async def register_playbook(self, payload: Payload):
        _ = await payload.command_write(command_type=REGISTER_PLAYBOOK, plugin=AppKey.REGISTRAR)

    async def register_plugin(self, payload: Payload):
        _ = await payload.command_write(command_type=REGISTER_PLUGIN, plugin=AppKey.REGISTRAR)

    async def register_playbook_execution_request(self, payload: Payload):
        _ = await payload.command_write(command_type=REGISTER_PLAYBOOK_EXECUTION, plugin=AppKey.REGISTRAR)

    async def emit_playbook_command(self, payload: Payload):
        logger.info(payload.nats_reference)
        payload.add_metadata(key=AppKey.PAYLOAD_REFERENCE, value=payload.nats_reference.to_dict())
        logger.debug(payload.get_value(AppKey.METADATA))
        stream = payload.get_value("metadata.payloadReference.nats_msg_metadata.stream")
        seq = payload.get_value("metadata.payloadReference.nats_msg_metadata.sequence.stream")
        logger.debug(f"stream: {stream}, seq: {seq}")
        nats_msg_data: RawStreamMsg = await self.get_msg(stream=stream, sequence=seq)
        playbook_blueprint = Playbook.unmarshal(binary_data=nats_msg_data.data, nats_pool=self.nats_pool)
        logger.debug(playbook_blueprint)

        match payload.get_value(Metadata.EVENT_TYPE):
            case "PlaybookStarted":
                logger.info(playbook_blueprint)
            case "PlaybookTaskExecuted":
                logger.info(playbook_blueprint)
            case "PlaybookStepExecuted":
                logger.info(playbook_blueprint)
            case "PlaybookCompleted":
                logger.info(playbook_blueprint)
            case "playbookFailed":
                logger.info(playbook_blueprint)

    async def switch(self, payload: Payload):

        match payload.get_value(Metadata.EVENT_TYPE):
            case "PlaybookRegistrationRequested":
                await self.register_playbook(payload=payload)

            case "PluginRegistrationRequested":
                await self.register_plugin(payload=payload)

            case "PlaybookExecutionRequested":
                await self.register_playbook_execution_request(payload=payload)

            case "PlaybookExecutionRegistered":
                await self.emit_playbook_command(payload=payload)


if __name__ == "__main__":
    args = parse_args(
        description="NoETL Dispatcher Plugin",
        default_nats_url="nats://localhost:32222",
        default_nats_pool_size=10,
        default_plugin_name="dispatcher",
        default_nats_subscription_subject="noetl.event.dispatcher.>",
        default_nats_subscription_stream="noetl",
        default_nats_subscription_queue="noetl-dispatcher",
        default_nats_command_prefix="noetl.command",
        default_nats_command_stream="noetl",
        default_nats_event_prefix="noetl.event",
        default_nats_event_stream="noetl",
        default_prom_host="localhost",
        default_prom_port=9092
    )
    dispatcher_plugin = Dispatcher()
    dispatcher_plugin.initialize_nats_pool(
        NatsConfig(
            nats_url=args.nats_url,
            nats_pool_size=args.nats_pool_size
        ))
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(dispatcher_plugin.run(args=args))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.info(f"Dispatcher plugin error: {str(e)}.")
    finally:
        loop.run_until_complete(dispatcher_plugin.shutdown())
