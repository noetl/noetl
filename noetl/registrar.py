import asyncio
from plugin import Plugin, Payload, parse_args, Namespace, logger, NatsConfig, NatsStreamReference
from playbook import Playbook



class Registrar(Plugin):

    async def playbook_register(self,
                                payload_data: Payload,
                                nats_reference: NatsStreamReference,
                                args: Namespace):
        payload_kv_value = Payload.kv(
            payload_data={
                "value": payload_data.get_value("playbook_base64"),
                "metadata": payload_data.get_value("metadata") | {"value_type": "base64"}
            },
            nats_pool=await self.get_nats_pool()
        )
        revision_number = await self.playbook_put(key=payload_data.get_value("metadata.playbook_name"),
                                                  value=payload_kv_value.encode())
        await self.publish_event(
            payload_orig=payload_data,
            payload_data={
                "revision_number": revision_number,
                "playbook_base64": payload_data.get_value("playbook_base64"),
                "metadata": payload_data.get_value("metadata", exclude=list(["event_type", "command_type"])) |
                            {"nats_reference": nats_reference.to_dict(), "event_type": "PlaybookRegistered"}
            },
            subject_prefix=f"{args.nats_command_prefix}.dispatcher",
            stream=args.nats_subscription_stream)


    async def plugin_register(self,
                              payload_data: Payload,
                              nats_reference: NatsStreamReference,
                              args: Namespace):
        payload_kv_value = Payload.kv(
            payload_data={
                "value": {
                    "plugin_name": payload_data.get_value("plugin_name"),
                    "image_url": payload_data.get_value("image_url")
                },
                "metadata": payload_data.get_value("metadata") | {"value_type": "dict"}
            },
            nats_pool=await self.get_nats_pool()
        )
        revision_number = await self.plugin_put(key=payload_data.get_value("plugin_name"),
                                                value=payload_kv_value.encode())
        await self.publish_event(
            payload_orig=payload_data,
            payload_data={
                "revision_number": revision_number,
                "plugin_name": payload_data.get_value("plugin_name"),
                "metadata": payload_data.get_value("metadata", exclude=list(["event_type", "command_type"])) | {
                    "nats_reference": nats_reference.to_dict(), "event_type": "PluginRegistered"}
            },
            subject_prefix=f"{args.nats_command_prefix}.dispatcher",
            stream=args.nats_subscription_stream)

    async def run_playbook_register(self,
                                    payload_data: Payload,
                                    nats_reference: NatsStreamReference,
                                    args: Namespace):
        key = payload_data.get_value("playbook_name")
        payload_reference = payload_data.get_payload_reference()
        playbook_kv_payload = Payload.decode(await self.playbook_get(key))
        playbook_template = playbook_kv_payload.yaml_value("value")
        if playbook_template == "VALUE NOT FOUND":
            await self.publish_event(
                payload_orig=payload_data,
                payload_data={
                    "error": f"Playbook template {key} was not found",
                    "metadata": payload_data.get_value("metadata", exclude=list(["command_type", "event_type"])) |
                                {"nats_reference": nats_reference.to_dict(),
                                 "event_type": "RunPlaybookRegistrationFailed"}
                },
                subject_prefix=f"{args.nats_command_prefix}.dispatcher",
                stream=args.nats_subscription_stream)
        else:
            playbook = Playbook(
                playbook_template=playbook_template,
                playbook_input=payload_data.get_value("playbook_input"),
                playbook_metadata=playbook_kv_payload.get_value("metadata", "METADATA NOT FOUND"),
                playbook_id=payload_data.get_origin(),
                nats_pool=self.nats_pool
            )
            playbook_reference = await playbook.register()
            await self.publish_event(
                payload_orig=payload_data,
                payload_data={
                    "playbook_reference": playbook_reference,
                    "playbook_metadata": playbook_kv_payload.get_value("metadata", "METADATA NOT FOUND"),
                    "metadata": payload_data.get_value("metadata", exclude=list(["command_type", "event_type"])) |
                                {"nats_reference": nats_reference.to_dict(), "event_type": "RunPlaybookRegistered"}
                },
                subject_prefix=f"{args.nats_command_prefix}.dispatcher",
                stream=args.nats_subscription_stream)

    async def switch(self,
                     payload: Payload,
                     nats_reference: NatsStreamReference,
                     args: Namespace):
        match payload.get_value("metadata.command_type"):
            case "RegisterPlaybook":
                await self.playbook_register(
                    payload_data=payload,
                    nats_reference=nats_reference,
                    args=args)
            case "RegisterPlugin":
                await self.plugin_register(
                    payload_data=payload,
                    nats_reference=nats_reference,
                    args=args)
            case "RegisterRunPlaybook":
                await self.run_playbook_register(
                    payload_data=payload,
                    nats_reference=nats_reference,
                    args=args)


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
