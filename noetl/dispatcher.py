import asyncio
import sys
from plugin import Plugin, parse_args
from payload import Payload
from loguru import logger
from natstream import NatsConfig


class Dispatcher(Plugin):

    async def workflow_register(self, payload_data: Payload):
        payload = Payload.create(
            payload_data={"workflow_base64": payload_data.get_value("workflow_base64")} | \
                         {"metadata": payload_data.get_value("metadata")} | \
                         {"command_type": "RegisterWorkflow"},
            prefix="metadata",
            reference=payload_data.get_value("metadata.identifier")
        )
        logger.debug(payload)

        await self.command_write(
            subject=f"registrar.{payload.get_value('metadata.identifier')}",
            message=payload.encode()
        )

    async def switch(self, payload: Payload):
        if payload.get_value("event_type") == "WorkflowRegistrationRequested":
            await self.workflow_register(payload)


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
