import asyncio
import sys
from plugin import Plugin, parse_args
from payload import Payload
from loguru import logger
from natstream import NatsConfig, NatsStreamReference
from playbook import Playbook


class Dispatcher(Plugin):

    async def playbook_register(self, payload_data: Payload, nats_reference: NatsStreamReference):
        new_payload_data = {
            "playbook_name": payload_data.get_value("playbook_name"),
            "playbook_base64": payload_data.get_value("playbook_base64"),
            "metadata": payload_data.get_value("metadata", exclude=["event_type", "command_type"]) |
                        {"command_type": "RegisterPlaybook",
                         "nats_reference": nats_reference.to_dict(),
                         },
        }
        await self.write_payload(payload_orig=payload_data, payload_data=new_payload_data, subject_prefix="registrar")

    async def plugin_register(self, payload_data: Payload, nats_reference: NatsStreamReference):
        new_payload_data = {
            "plugin_name": payload_data.get_value("plugin_name"),
            "image_url": payload_data.get_value("image_url"),
            "metadata": payload_data.get_value("metadata", exclude=["event_type", "command_type"]) |
                        {"command_type": "RegisterPlugin",
                         "nats_reference": nats_reference.to_dict(),
                         },
        }
        await self.write_payload(payload_orig=payload_data, payload_data=new_payload_data, subject_prefix="registrar")

    async def run_playbook_register(
            self,
            payload_data: Payload,
            nats_reference: NatsStreamReference
    ):

        payload_reference = payload_data.get_payload_reference()
        # payload: Payload = Payload.create(
        #     payload_data={
        #         "playbook_name": payload_data.get_value("playbook_name"),
        #         "playbook_input": payload_data.get_value("playbook_input", {"input": "NO DATA PROVIDED"}),
        #         "metadata": payload_data.get_value("metadata", exclude=list(["event_type", "command_type"])) |
        #                     {"command_type": "RegisterRunPlaybook", "nats_reference": nats_reference.to_dict()},
        #     },
        #     origin=payload_reference.get("origin"),
        #     reference=payload_reference.get("identifier"),
        #     nats_pool=await self.get_nats_pool()
        # )

        new_payload_data = {
            "playbook_name": payload_data.get_value("playbook_name"),
            "playbook_input": payload_data.get_value("playbook_input", {"input": "NO DATA PROVIDED"}),
            "metadata": payload_data.get_value("metadata", exclude=list(["event_type", "command_type"])) |
                        {"command_type": "RegisterRunPlaybook", "nats_reference": nats_reference.to_dict()},
        }
        await self.write_payload(payload_orig=payload_data, payload_data=new_payload_data, subject_prefix="registrar")
        # ack = await payload.command_write(
        #     subject=f"registrar.{payload.get_subject_ref()}",
        #     message=payload.encode()
        # )

    async def generate_playbook_command(
            self,
            payload_data: Payload,
            nats_reference: NatsStreamReference
    ):
        playbook = Playbook.create(
            payload_data=payload_data,
            nats_pool=await self.get_nats_pool()
        )

        event_type = payload_data.get_value("metadata.event_type")

        if event_type == "PlaybookStarted":
            logger.info(payload_data)
        elif event_type == "PlaybookTaskExecuted":
            logger.info(payload_data)
        elif event_type == "PlaybookStepExecuted":
            logger.info(payload_data)
        elif event_type == "PlaybookCompleted":
            logger.info(payload_data)
        elif event_type == "playbookFailed":
            logger.info(payload_data)

    async def switch(self,
                     payload: Payload,
                     nats_reference: NatsStreamReference
                     ):

        match payload.get_value("metadata.event_type"):
            case "PlaybookRegistrationRequested":
                await self.playbook_register(payload_data=payload, nats_reference=nats_reference)
            case "PluginRegistrationRequested":
                await self.plugin_register(payload_data=payload, nats_reference=nats_reference)
            case "PlaybookExecutionRequested":
                await self.run_playbook_register(payload_data=payload, nats_reference=nats_reference)
            case "RunPlaybookRegistered":
                await self.generate_playbook_command(payload_data=payload, nats_reference=nats_reference)


if __name__ == "__main__":
    args = parse_args(
        description="NoETL Dispatcher Plugin",
        default_nats_url="nats://localhost:32222",
        default_nats_pool_size=10,
        default_prom_host="localhost",
        default_prom_port=9091
    )
    dispatcher_plugin = Dispatcher()
    dispatcher_plugin.initialize_nats_pool(NatsConfig(
        nats_url=args.nats_url,
        nats_pool_size=args.nats_pool_size
    ))
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(dispatcher_plugin.run(args=args, subject_prefix="event.dispatcher"))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.info(f"Dispatcher plugin error: {str(e)}.")
    finally:
        loop.run_until_complete(dispatcher_plugin.shutdown())
