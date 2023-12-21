import asyncio
from plugin import Plugin, parse_args
from payload import Payload
from playbook import Playbook
from loguru import logger
from natstream import NatsConfig, NatsStreamReference


class Registrar(Plugin):

    async def playbook_register(self, payload_data: Payload, nats_reference: NatsStreamReference):
        payload_kv_value = Payload.kv(
            payload_data={
                "value": payload_data.get_value("playbook_base64"),
                "metadata": payload_data.get_value("metadata") | {"value_type": "base64"}
            },
            nats_pool=await self.get_nats_pool()
        )
        revision_number = await self.playbook_put(key=payload_data.get_value("metadata.playbook_name"),
                                                  value=payload_kv_value.encode())
        await self.write_event_payload(
            payload_orig=payload_data,
            payload_data={
                "revision_number": revision_number,
                "playbook_base64": payload_data.get_value("playbook_base64"),
                "metadata": payload_data.get_value("metadata", exclude=list(["event_type", "command_type"])) |
                            {"nats_reference": nats_reference.to_dict(), "event_type": "PlaybookRegistered"}
            },
            subject="dispatcher"
        )

    async def plugin_register(self, payload_data: Payload, nats_reference: NatsStreamReference):
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
        await self.write_event_payload(
            payload_orig=payload_data,
            payload_data={
                "revision_number": revision_number,
                "plugin_name": payload_data.get_value("plugin_name"),
                "metadata": payload_data.get_value("metadata", exclude=list(["event_type", "command_type"])) | {
                    "nats_reference": nats_reference.to_dict(), "event_type": "PluginRegistered"}
            },
            subject="dispatcher"
        )

    async def run_playbook_register(self, payload_data: Payload, nats_reference: NatsStreamReference):
        key = payload_data.get_value("playbook_name")
        payload_reference = payload_data.get_payload_reference()
        playbook_kv_payload = Payload.decode(await self.playbook_get(key))
        playbook_template = playbook_kv_payload.yaml_value("value")
        if playbook_template == "VALUE NOT FOUND":
            await self.write_event_payload(
                payload_orig=payload_data,
                payload_data={
                    "error": f"Playbook template {key} was not found",
                    "metadata": payload_data.get_value("metadata", exclude=list(["command_type", "event_type"])) |
                                {"nats_reference": nats_reference.to_dict(),
                                 "event_type": "RunPlaybookRegistrationFailed"}
                },
                subject="dispatcher"
            )
        else:
            playbook = Playbook(
                playbook_template=playbook_template,
                playbook_input=payload_data.get_value("playbook_input"),
                playbook_metadata=playbook_kv_payload.get_value("metadata", "METADATA NOT FOUND"),
                playbook_id=payload_data.get_origin_ref(),
                nats_pool=self.nats_pool
            )
            playbook_reference = await playbook.register()
            await self.write_event_payload(
                payload_orig=payload_data,
                payload_data={
                    "playbook_reference": playbook_reference,
                    "playbook_metadata": playbook_kv_payload.get_value("metadata", "METADATA NOT FOUND"),
                    "metadata": payload_data.get_value("metadata", exclude=list(["command_type", "event_type"])) |
                                {"nats_reference": nats_reference.to_dict(), "event_type": "RunPlaybookRegistered"}
                },
                subject="dispatcher"
            )

    async def switch(self,
                     payload: Payload,
                     nats_reference: NatsStreamReference
                     ):
        match payload.get_value("metadata.command_type"):
            case "RegisterPlaybook":
                await self.playbook_register(payload_data=payload, nats_reference=nats_reference)
            case "RegisterPlugin":
                await self.plugin_register(payload_data=payload, nats_reference=nats_reference)
            case "RegisterRunPlaybook":
                await self.run_playbook_register(payload_data=payload, nats_reference=nats_reference)


if __name__ == "__main__":
    args = parse_args(
        description="NoETL Registrar Plugin",
        default_nats_url="nats://localhost:32222",
        default_nats_pool_size=10,
        default_prom_host="localhost",
        default_prom_port=9092
    )
    registrar_plugin = Registrar()
    registrar_plugin.initialize_nats_pool(NatsConfig(
        nats_url=args.nats_url,
        nats_pool_size=args.nats_pool_size
    ))
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(registrar_plugin.run(args=args, plugin_name="registrar"))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.info(f"Dispatcher plugin error: {str(e)}.")
    finally:
        loop.run_until_complete(registrar_plugin.shutdown())
