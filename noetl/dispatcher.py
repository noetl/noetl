import asyncio
from plugin import Plugin, Payload, parse_args, Namespace, logger, NatsConfig, NatsStreamReference
from playbook import Playbook


class Dispatcher(Plugin):

    async def playbook_register(self,
                                payload_data: Payload,
                                nats_reference: NatsStreamReference,
                                args: Namespace):
        command_payload_data = {
            "playbook_name": payload_data.get_value("playbook_name"),
            "playbook_base64": payload_data.get_value("playbook_base64"),
            "metadata": payload_data.get_value("metadata", exclude=["event_type", "command_type"]) |
                        {"command_type": "RegisterPlaybook",
                         "nats_reference": nats_reference.to_dict(),
                         },
        }
        await self.publish_command(
            payload_orig=payload_data,
            payload_data=command_payload_data,
            subject_prefix=f"{args.nats_command_prefix}.registrar",
            stream=args.nats_subscription_stream)

    async def plugin_register(self,
                              payload_data: Payload,
                              nats_reference: NatsStreamReference,
                              args: Namespace):
        command_payload_data = {
            "plugin_name": payload_data.get_value("plugin_name"),
            "image_url": payload_data.get_value("image_url"),
            "metadata": payload_data.get_value("metadata", exclude=["event_type", "command_type"]) |
                        {"command_type": "RegisterPlugin",
                         "nats_reference": nats_reference.to_dict(),
                         },
        }
        await self.publish_command(
            payload_orig=payload_data,
            payload_data=command_payload_data,
            subject_prefix=f"{args.nats_command_prefix}.registrar",
            stream=args.nats_subscription_stream)

    async def run_playbook_register(self,
                                    payload_data: Payload,
                                    nats_reference: NatsStreamReference,
                                    args: Namespace):
        payload_reference = payload_data.get_reference()
        command_payload_data = {
            "playbook_name": payload_data.get_value("playbook_name"),
            "playbook_input": payload_data.get_value("playbook_input", {"input": "NO DATA PROVIDED"}),
            "metadata": payload_data.get_value("metadata", exclude=list(["event_type", "command_type"])) |
                        {"command_type": "RegisterRunPlaybook",
                         "nats_reference": nats_reference.to_dict(),
                         "payload_reference": payload_reference},
        }
        await self.publish_command(
            payload_orig=payload_data,
            payload_data=command_payload_data,
            subject_prefix=f"{args.nats_command_prefix}.registrar",
            stream=args.nats_subscription_stream)

    async def process_playbook(self,
                               payload_data: Payload,
                               nats_reference: NatsStreamReference,
                               args: Namespace):
        logger.info(nats_reference)
        playbook_reference = payload_data.get_value("playbook_reference")
        nats_msg_data = await self.nats_read_subject(playbook_reference)
        playbook_blueprint = Playbook.unmarshal(binary_data=nats_msg_data, nats_pool=self.nats_pool)

        logger.debug(playbook_blueprint)

        match payload_data.get_value("metadata.event_type"):
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

        match payload.get_value("metadata.event_type"):
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
