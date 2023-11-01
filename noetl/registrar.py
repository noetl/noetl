import asyncio
from plugin import Plugin, parse_args
from record import Record
from loguru import logger
from natstream import NatsConfig


class Registrar(Plugin):

    async def create_workflow_catalog(self):
        await self.nats_pool.catalog_create(catalog_name="workflows")

    async def delete_workflow_catalog(self):
        await self.nats_pool.catalog_delete(catalog_name="workflows")

    async def add_workflow(self, record: Record):
        return await self.nats_pool.catalog_add(catalog_name="workflows", record=record)

    async def del_workflow(self, key: str):
        await self.nats_pool.catalog_del(catalog_name="workflows", key=key)

    async def get_workflow(self, key: str):
        return await self.nats_pool.catalog_get(catalog_name="workflows", key=key)

    async def create_plugin_catalog(self):
        await self.nats_pool.catalog_create(catalog_name="plugins")

    async def delete_plugin_catalog(self):
        await self.nats_pool.catalog_delete(catalog_name="plugins")

    async def add_plugin(self, record: Record):
        await self.nats_pool.catalog_add(catalog_name="plugins", record=record)

    async def get_plugin(self, key: str):
        await self.nats_pool.catalog_get(catalog_name="plugins", key=key)

    async def workflow_register(self, data: Record):
        key = await self.add_workflow(record=data)
        event = "WorkflowRegistered"
        record = Record.create(
            name=data.name.value,
            metadata=data.metadata.value | {"event": event},
            reference=data.identifier,
            payload=data.payload.value
        )
        logger.debug(record)

        await self.nats_write(
            subject=f"event.result.{record.identifier}",
            message=record.serialize()
        )

    async def switch(self, data):
        if data.metadata.value.get("event_type") == "WorkflowRegistrationRequested":
            await self.workflow_register(data)


if __name__ == "__main__":
    args = parse_args(
        description="NoETL Registrar Service",
        default_nats_url="nats://localhost:32645",
        default_nats_pool_size=10,
        default_prom_host="localhost",
        default_prom_port=8000
    )
    registrar = Registrar.create(NatsConfig(nats_url=args.nats_url, nats_pool_size=args.nats_pool_size))
    asyncio.run(registrar.run(args, subject_prefix="command.registrar"))
