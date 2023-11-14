import asyncio
import sys
from plugin import Plugin, parse_args
from payload import Payload
from loguru import logger
from natstream import NatsConfig, NatsStreamReference


class Dispatcher(Plugin):

    async def workflow_register(self,
                                payload_data: Payload,
                                nats_reference: NatsStreamReference
                                ):
        origin_ref = payload_data.get_value("origin_ref")
        payload = Payload.create(
            payload_data={
                "workflow_base64": payload_data.get_value("workflow_base64"),
                "metadata": payload_data.get_value("metadata") | nats_reference.to_dict(),
                "command_type": "RegisterWorkflow"
            },
            origin_ref=origin_ref,
            prefix="metadata",
            reference=payload_data.get_value("metadata.identifier")
        )
        logger.debug(payload)

        await self.command_write(
            subject=f"registrar.{origin_ref}",
            message=payload.encode()
        )

    async def plugin_register(self,
                              payload_data: Payload,
                              nats_reference: NatsStreamReference
                              ):
        origin_ref = payload_data.get_value("origin_ref")
        payload = Payload.create(
            payload_data={
                "plugin_name": payload_data.get_value("plugin_name"),
                "image_url": payload_data.get_value("image_url"),
                "metadata": payload_data.get_value("metadata") | nats_reference.to_dict(),
                "command_type": "RegisterPlugin"
            },
            origin_ref=origin_ref,
            prefix="metadata",
            reference=payload_data.get_value("metadata.identifier")
        )
        logger.debug(payload)

        await self.command_write(
            subject=f"registrar.{origin_ref}",
            message=payload.encode()
        )

    async def switch(self,
                     payload: Payload,
                     nats_reference: NatsStreamReference
                     ):
        match payload.get_value("event_type"):
            case "WorkflowRegistrationRequested":
                await self.workflow_register(payload_data=payload, nats_reference=nats_reference)
            case "PluginRegistrationRequested":
                await self.plugin_register(payload_data=payload, nats_reference=nats_reference)


if __name__ == "__main__":
    args = parse_args(
        description="NoETL Dispatcher Service",
        default_nats_url="nats://localhost:32645",
        default_nats_pool_size=10,
        default_prom_host="localhost",
        default_prom_port=9091
    )
    try:
        dispatcher = Dispatcher.create(NatsConfig(nats_url=args.nats_url, nats_pool_size=args.nats_pool_size))
        asyncio.run(dispatcher.run(args, subject_prefix="event.dispatcher"))
    except KeyboardInterrupt:
        sys.exit()
    except Exception as e:
        logger.info(f"Dispatcher error: {str(e)}.")
