import asyncio
import nats
from dataclasses import dataclass
from nats.aio.errors import ErrTimeout
from loguru import logger
from record import Record, RecordField


@dataclass
class NatsConfig:
    nats_url: str = "nats://localhost:32645"
    nats_pool_size: int = 10


class NatsConnectionPool:
    def __init__(self, config: NatsConfig):
        self.config: NatsConfig = config
        self.pool = asyncio.Queue()

    async def get(self):
        try:
            if self.pool.empty():
                nc = await nats.connect(self.config.nats_url)
                return nc
            else:
                return await self.pool.get()
        except ErrTimeout as e:
            logger.error(f"NATS connection timeout error: {e}")
            raise
        except Exception as e:
            logger.error(f"NATS connection error: {e}")
            raise

    def get_pool_size(self):
        return self.config.nats_pool_size

    async def put(self, nc):
        try:
            await self.pool.put(nc)
        except Exception as e:
            logger.error(f"NATS connection error to put back to pool: {e}")
            raise

    async def execute(self, func):
        nc = await self.get()
        if nc is None:
            return
        try:
            js = nc.jetstream()
            return await func(js)
        except ErrTimeout as e:
            logger.error(f"NATS JetStream timeout error: {e}")
            raise
        except Exception as e:
            logger.error(f"NATS JetStream error: {e}")
            raise
        finally:
            await self.put(nc)

    def connection(self):
        return self._ConnectionContextManager(self)

    async def publish(self, subject, message):
        async with self.connection() as js:
            ack = await js.publish(f"{subject}", message)
        return ack

    async def close_pool(self):
        while not self.pool.empty():
            nc = await self.pool.get()
            try:
                await nc.close()
            except Exception as e:
                logger.error(f"NATS connection closing error: {e}")
            else:
                logger.info("NATS connection closed.")
        logger.info("NATS connections in the pool closed.")

    async def catalog_create(self, catalog_name: str):
        async with self.connection() as nc:
            try:
                catalog = await nc.create_key_value(bucket=catalog_name)
                logger.info(f"Catalog {catalog_name} created.")
                return catalog
            except Exception as e:
                print(f"Catalog create error: {e}")

    async def catalog_delete(self, catalog_name: str):
        async with self.connection() as nc:
            try:
                catalog = await nc.create_key_value(catalog_name)
                await catalog.delete(catalog_name)
                logger.info(f"Catalog {catalog_name} deleted.")
            except Exception as e:
                print(f"Catalog delete error: {e}")

    async def catalog_add(self, catalog_name: str, record: Record):
        async with self.connection() as nc:
            try:
                # catalog = await nc.kv(catalog_name)
                catalog = await nc.create_key_value(bucket=catalog_name)
                await catalog.put(record.name.value, record.payload.serialize())
                entry = await catalog.get(record.name.value)
                entry_value = RecordField.deserialize(entry.value)
                logger.debug(f"KeyValue.Entry: key={entry.key}, value={entry_value}")
                return entry.key
            except Exception as e:
                logger.error(f"Catalog {catalog_name} failed to add record {record}. Error: {e}")

    async def catalog_get(self, catalog_name, key: str):
        async with self.connection() as nc:
            try:
                catalog = await nc.create_key_value(bucket=catalog_name)
                entry = await catalog.get(key)
                entry_value = RecordField.deserialize(entry.value)
                logger.debug(f"KeyValue.Entry: key={entry.key}, value={entry_value}")
                return entry.value
            except Exception as e:
                logger.error(f"Catalog {catalog_name} failed to get record {key}. Error: {e}")

    async def catalog_del(self, catalog_name, key: str):
        async with self.connection() as nc:
            try:
                catalog = await nc.create_key_value(bucket=catalog_name)
                await catalog.delete(key)
                logger.debug(f"Catalog {catalog_name} record {key} deleted")
            except Exception as e:
                logger.error(f"Catalog {catalog_name} failed to delete record {key}. Error: {e}")

    class _ConnectionContextManager:
        def __init__(self, pool):
            self.pool = pool
            self.nc = None

        async def __aenter__(self):
            self.nc = await self.pool.get()
            if self.nc is None:
                raise Exception("Failed to get NATS connection")
            return self.nc.jetstream()

        async def __aexit__(self, exc_type, exc_value, traceback):
            await self.pool.put(self.nc)


nats_pool: NatsConnectionPool | None = None


def get_nats_pool():
    global nats_pool
    return nats_pool


async def initialize_nats_pool(nats_config: NatsConfig):
    global nats_pool
    nats_pool = NatsConnectionPool(
        config=nats_config
    )


if __name__ == "__main__":
    nats_config: NatsConfig = NatsConfig(nats_url="nats://localhost:32645", nats_pool_size=10)
    nats_pool = NatsConnectionPool(config=nats_config)


    async def test():
        async def func(js):
            ack = await js.publish('test.greeting', b'Hello JS!')
            logger.info(f'Ack: stream={ack.stream}, sequence={ack.seq}')

        return await nats_pool.execute(func)


    async def _main():
        result = await test()
        print(result)
        await nats_pool.close_pool()


    asyncio.run(_main())
