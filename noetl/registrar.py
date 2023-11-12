import asyncio
import sys
from plugin import Plugin, parse_args
from payload import Payload
from loguru import logger
from natstream import NatsConfig


class Registrar(Plugin):

    async def workflow_register(self, payload_data: Payload):
        key = payload_data.get_value("metadata.workflow_name")
        payload_kv_value = Payload.kv(
            {
                "workflow_base64": payload_data.get_value("workflow_base64"),
                "metadata": payload_data.get_value("metadata")
            }
        )
        revision_number = await self.workflow_put(key=key, value=payload_kv_value.encode())
        event = "WorkflowRegistered"
        payload = Payload.create(
            payload_data={
                "revision_number": revision_number,
                "metadata": payload_data.get_value("metadata"),
                "event_type": "WorkflowRegistered"
            },
            prefix="metadata",
            reference=payload_data.get_value("metadata.identifier")
        )
        logger.debug(payload)

        await self.event_write(
            subject=f"registrar.{payload.get_value('metadata.identifier')}",
            message=payload.encode()
        )

    async def switch(self, payload: Payload):
        if payload.get_value("command_type") == "RegisterWorkflow":
            await self.workflow_register(payload)


if __name__ == "__main__":
    args = parse_args(
        description="NoETL Registrar Service",
        default_nats_url="nats://localhost:32645",
        default_nats_pool_size=10,
        default_prom_host="localhost",
        default_prom_port=9092
    )
    try:
        registrar = Registrar.create(NatsConfig(nats_url=args.nats_url, nats_pool_size=args.nats_pool_size))
        asyncio.run(registrar.run(args, subject_prefix="command.registrar"))
    except KeyboardInterrupt:
        sys.exit()
    except Exception as e:
        logger.info(f"Dispatcher error: {str(e)}.")
