import asyncio
from plugin import Plugin, parse_args, Namespace, logger, NatsConfig, NatsStreamReference
from payload import Payload, AppKey, CommandType, Metadata, RawStreamMsg
from playbook import Playbook


class Dispatcher(Plugin):

    async def playbook_register(self,
                                payload_data: Payload,
                                nats_reference: NatsStreamReference,
                                args: Namespace):
        command_payload_data = {
            AppKey.PLUGIN_NAME: payload_data.get_value(AppKey.PLAYBOOK_NAME),
            AppKey.PLAYBOOK_BASE64: payload_data.get_value(AppKey.PLAYBOOK_BASE64),
            AppKey.METADATA: payload_data.get_value(AppKey.METADATA, exclude=[AppKey.EVENT_TYPE, AppKey.COMMAND_TYPE]) |
                        {AppKey.COMMAND_TYPE: CommandType.REGISTER_PLAYBOOK,
                         AppKey.NATS_REFERENCE: nats_reference.to_dict(),
                         },
        }
        await self.publish_command(
            payload_orig=payload_data,
            payload_data=command_payload_data,
            subject_prefix=f"{args.nats_command_prefix}.{AppKey.REGISTRAR}",
            stream=args.nats_subscription_stream)

    async def plugin_register(self,
                              payload_data: Payload,
                              nats_reference: NatsStreamReference,
                              args: Namespace):
        command_payload_data = {
            AppKey.PLUGIN_NAME: payload_data.get_value(AppKey.PLUGIN_NAME),
            AppKey.IMAGE_URL: payload_data.get_value(AppKey.IMAGE_URL),
            AppKey.METADATA: payload_data.get_value(AppKey.METADATA, exclude=[AppKey.EVENT_TYPE, AppKey.COMMAND_TYPE]) |
                        {AppKey.COMMAND_TYPE: CommandType.REGISTER_PLUGIN,
                         AppKey.NATS_REFERENCE: nats_reference.to_dict(),
                         },
        }
        await self.publish_command(
            payload_orig=payload_data,
            payload_data=command_payload_data,
            subject_prefix=f"{args.nats_command_prefix}.{AppKey.REGISTRAR}",
            stream=args.nats_subscription_stream)

    async def run_playbook_register(self,
                                    payload_data: Payload,
                                    nats_reference: NatsStreamReference,
                                    args: Namespace):
        payload_reference = payload_data.get_reference()
        command_payload_data = {
            AppKey.PLAYBOOK_NAME: payload_data.get_value(AppKey.PLAYBOOK_NAME),
            AppKey.PLAYBOOK_INPUT: payload_data.get_value(path=AppKey.PLAYBOOK_INPUT, default={AppKey.INPUT: AppKey.NO_DATA_PROVIDED}),
            AppKey.METADATA: payload_data.get_value(AppKey.METADATA, exclude=list([AppKey.EVENT_TYPE, AppKey.COMMAND_TYPE])) |
                        {AppKey.COMMAND_TYPE: CommandType.REGISTER_RUN_PLAYBOOK,
                         AppKey.NATS_REFERENCE: nats_reference.to_dict(),
                         AppKey.PAYLOAD_REFERENCE: payload_reference},
        }
        await self.publish_command(
            payload_orig=payload_data,
            payload_data=command_payload_data,
            subject_prefix=f"{args.nats_command_prefix}.{AppKey.REGISTRAR}",
            stream=args.nats_subscription_stream)

    async def process_playbook(self,
                               payload_data: Payload,
                               nats_reference: NatsStreamReference,
                               args: Namespace):
        logger.info(nats_reference)
        playbook_reference = payload_data.get_keyval(path=AppKey.PLAYBOOK_REFERENCE)
        nats_msg_data: RawStreamMsg = await self.get_msg(stream=playbook_reference.get_value("stream"), sequence=playbook_reference.get_value("seq"))
        logger.debug(nats_msg_data.as_dict())
        playbook_blueprint = Playbook.unmarshal(binary_data=nats_msg_data.data, nats_pool=self.nats_pool)
        logger.debug(playbook_blueprint)

        match payload_data.get_value(Metadata.EVENT_TYPE):
            case "PlaybookStarted":
                logger.info(playbook_blueprint)
            case "PlaybookTaskExecuted":
                logger.info(playbook_blueprint)
            case  "PlaybookStepExecuted":
                logger.info(playbook_blueprint)
            case  "PlaybookCompleted":
                logger.info(playbook_blueprint)
            case  "playbookFailed":
                logger.info(playbook_blueprint)

    async def switch(self,
                     payload: Payload,
                     nats_reference: NatsStreamReference,
                     args: Namespace
                     ):

        match payload.get_value(Metadata.EVENT_TYPE):
            case "PlaybookRegistrationRequested":
                await self.playbook_register(
                    payload_data=payload,
                    nats_reference=nats_reference,
                    args=args)
            case "PluginRegistrationRequested":
                await self.plugin_register(
                    payload_data=payload,
                    nats_reference=nats_reference,
                    args=args)
            case "PlaybookExecutionRequested":
                await self.run_playbook_register(
                    payload_data=payload,
                    nats_reference=nats_reference,
                    args=args)
            case "RunPlaybookRegistered":
                await self.process_playbook(
                    payload_data=payload,
                    nats_reference=nats_reference,
                    args=args)


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
