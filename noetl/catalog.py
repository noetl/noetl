from loguru import logger
from dataclasses import dataclass
from natstream import NatsConnectionPool
from record import Record, RecordField


@dataclass
class Catalog:
    nats_pool: NatsConnectionPool

    @classmethod
    def create(cls, nats_pool: NatsConnectionPool):
        return cls(
            nats_pool=nats_pool
        )

    async def create_catalog(self, catalog_name: str):
        async with self.nats_pool.connection() as nc:
            try:
                catalog = await nc.create_key_value(bucket=catalog_name)
                logger.info(f"Catalog {catalog_name} created.")
                return catalog
            except Exception as e:
                print(f"Catalog error: {e}")

    async def delete_catalog(self, catalog_name: str):
        async with self.nats_pool.connection() as nc:
            try:
                catalog = await nc.kv(catalog_name)
                await catalog.delete(catalog_name)
                logger.info(f"Catalog {catalog_name} deleted.")
            except Exception as e:
                print(f"Catalog error: {e}")

    async def add(self, catalog_name: str, record: Record):
        async with self.nats_pool.connection() as nc:
            try:
                catalog = await nc.kv(catalog_name)
                await catalog.put(record.name.value, record.payload.serialize())
                entry = await catalog.get(record.name.value)
                entry_value = RecordField.deserialize(entry.value)
                logger.debug(f"KeyValue.Entry: key={entry.key}, value={entry_value}")
            except Exception as e:
                logger.error(f"Catalog {catalog_name} failed to add record: {e}")

    async def get(self, catalog_name, key: str):
        async with self.nats_pool.connection() as nc:
            try:
                catalog = await nc.kv(catalog_name)
                entry = await catalog.get(key)
                entry_value = RecordField.deserialize(entry.value)
                logger.debug(f"KeyValue.Entry: key={entry.key}, value={entry_value}")
            except Exception as e:
                logger.error(f"Catalog {catalog_name} failed to get record: {e}")

    async def create_workflow_catalog(self):
        await self.create_catalog(catalog_name="workflows")

    async def delete_workflow_catalog(self):
        await self.delete_catalog(catalog_name="workflows")

    async def add_workflow(self, record: Record):
        await self.add(catalog_name="workflows", record=record)

    async def get_workflow(self, key: str):
        await self.get(catalog_name="workflows", key=key)

    async def create_plugin_catalog(self):
        await self.create_catalog(catalog_name="services")

    async def delete_plugin_catalog(self):
        await self.delete_catalog(catalog_name="services")

    async def add_plugin(self, record: Record):
        await self.add(catalog_name="services", record=record)

    async def get_plugin(self, key: str):
        await self.get(catalog_name="services", key=key)
