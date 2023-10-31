import asyncio
from noetl import NoETLHandler, parse_args
from record import Record
from loguru import logger
from natstream import NatsConfig


class Dispatcher(NoETLHandler):

    async def workflow_register(self, data: Record):
        command = "RegisterWorkflowConfig"
        record = Record.create(
            name=data.name.value,
            metadata=data.metadata.value | {"command": command},
            reference=data.identifier,
            payload=data.payload.value
        )
        logger.debug(record)

        await self.nats_write(
            subject=f"command.registrar.{record.identifier}",
            message=record.serialize()
        )

    async def switch(self, data):
        if data.metadata.value.get("event_type") == "WorkflowConfigRegistrationRequested":
            await self.workflow_register(data)


if __name__ == "__main__":
    args = parse_args(
        description="NoETL Dispatcher Service",
        default_nats_url="nats://localhost:32645",
        default_nats_pool_size=10,
        default_prom_host="localhost",
        default_prom_port=8000
    )
    dispatcher = Dispatcher.create(NatsConfig(nats_url=args.nats_url, nats_pool_size=args.nats_pool_size))
    asyncio.run(dispatcher.run(args, subject_prefix="event.dispatcher"))
