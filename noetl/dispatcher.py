import asyncio
import sys
from plugin import Plugin, parse_args
from payload import Payload, PayloadReference
from loguru import logger
from natstream import NatsConfig, NatsStreamReference


class Dispatcher(Plugin):

    async def workflow_register(
            self,
            payload_data: Payload,
            nats_reference: NatsStreamReference
    ):

        payload_reference = payload_data.get_payload_reference()
        payload: Payload = Payload.create(
            payload_data={
                "workflow_name": payload_data.get_value("workflow_name"),
                "workflow_base64": payload_data.get_value("workflow_base64"),
                "metadata": payload_data.get_value("metadata", exclude=list(["event_type","command_type"])) |
                {"command_type": "RegisterWorkflow", "nats_reference": nats_reference.to_dict()},
            },
            origin=payload_reference.get("origin"),
            reference=payload_reference.get("identifier"),
            nats_pool=await self.get_nats_pool()
        )
        ack = await payload.command_write(
            subject=f"registrar.{payload.get_subject_ref()}",
            message=payload.encode()
        )
        logger.debug(ack)

    async def plugin_register(
            self,
            payload_data: Payload,
            nats_reference: NatsStreamReference
    ):
        payload_reference: PayloadReference = payload_data.get_payload_reference()
        payload: Payload = Payload.create(
            payload_data={
                "plugin_name": payload_data.get_value("plugin_name"),
                "image_url": payload_data.get_value("image_url"),
                "metadata": payload_data.get_value("metadata",exclude=list(["event_type","command_type"])) |
                            {"nats_reference": nats_reference.to_dict()},
                "command_type": "RegisterWorkflow"
            },
            origin=payload_reference.origin,
            reference=payload_reference.identifier,
            nats_pool=await self.get_nats_pool()
        )
        ack = await payload.command_write(
            subject=f"registrar.{payload.get_subject_ref()}",
            message=payload.encode()
        )
        logger.debug(ack)

    async def run_workflow_register(
            self,
            payload_data: Payload,
            nats_reference: NatsStreamReference
    ):

        payload_reference = payload_data.get_payload_reference()
        payload: Payload = Payload.create(
            payload_data={
                "workflow_name": payload_data.get_value("workflow_name"),
                "workflow_input": payload_data.get_value("workflow_input", {"input": "NO DATA PROVIDED"}),
                "metadata": payload_data.get_value("metadata", exclude=list(["event_type","command_type"])) |
                {"command_type": "RegisterRunWorkflow", "nats_reference": nats_reference.to_dict()},
            },
            origin=payload_reference.get("origin"),
            reference=payload_reference.get("identifier"),
            nats_pool=await self.get_nats_pool()
        )
        ack = await payload.command_write(
            subject=f"registrar.{payload.get_subject_ref()}",
            message=payload.encode()
        )
        logger.debug(ack)

    async def generate_workflow_command(
            self,
            payload_data: Payload,
            nats_reference: NatsStreamReference
    ):

        payload_reference = payload_data.get_payload_reference()
        logger.info(payload_data)
        # payload: Payload = Payload.create(
        #     payload_data={
        #         "workflow_name": payload_data.get_value("workflow_name"),
        #         "workflow_input": payload_data.get_value("workflow_input", {"input": "NO DATA PROVIDED"}),
        #         "metadata": payload_data.get_value("metadata", exclude=list(["event_type","command_type"])) |
        #         {"command_type": "RegisterRunWorkflow", "nats_reference": nats_reference.to_dict()},
        #     },
        #     origin=payload_reference.get("origin"),
        #     reference=payload_reference.get("identifier"),
        #     nats_pool=await self.get_nats_pool()
        # )
        # ack = await payload.command_write(
        #     subject=f"registrar.{payload.get_subject_ref()}",
        #     message=payload.encode()
        # )
        # logger.debug(ack)

    async def switch(self,
                     payload: Payload,
                     nats_reference: NatsStreamReference
                     ):

        match payload.get_value("metadata.event_type"):
            case "WorkflowRegistrationRequested":
                await self.workflow_register(payload_data=payload, nats_reference=nats_reference)
            case "PluginRegistrationRequested":
                await self.plugin_register(payload_data=payload, nats_reference=nats_reference)
            case "WorkflowExecutionRequested":
                await self.run_workflow_register(payload_data=payload, nats_reference=nats_reference)
            case "RunWorkflowRegistered":
                await self.generate_workflow_command(payload_data=payload, nats_reference=nats_reference)


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
