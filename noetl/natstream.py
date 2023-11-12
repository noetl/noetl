import asyncio
import nats
from nats.js.api import StreamConfig
from dataclasses import dataclass
from nats.aio.errors import ErrTimeout
from loguru import logger


@dataclass
class NatsConfig:
    nats_url: str
    nats_pool_size: int


class NatsConnectionPool:
    _instance = None

    def __new__(cls, config: NatsConfig | None):
        if cls._instance is None:
            cls._instance = super(NatsConnectionPool, cls).__new__(cls)
            cls._instance.config = config
            cls._instance.pool = asyncio.Queue()
        else:
            raise Exception("NatsConnectionPool is a singleton")
        return cls._instance

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            raise Exception("NatsConnectionPool instance was not initialized.")
        return cls._instance

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

    async def truncate_stream(self, stream_name):
        try:
            async with self.connection() as js:
                await js.update_stream(name=stream_name, config=StreamConfig(max_msgs=0))
                print(f"Stream {stream_name} truncated.")
        except Exception as e:
            print(f"Error truncating stream: {e}")

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

    async def bucket_create(self, bucket_name: str):
        async with self.connection() as nc:
            try:
                bucket = await nc.create_key_value(bucket=bucket_name)
                logger.info(f"Bucket {bucket_name} created.")
                return bucket
            except Exception as e:
                print(f"Bucket create error: {e}")

    async def bucket_delete(self, bucket_name: str):
        async with self.connection() as nc:
            try:
                bucket = await nc.create_key_value(bucket_name)
                await bucket.delete(bucket_name)
                logger.info(f"Bucket {bucket_name} deleted.")
            except Exception as e:
                print(f"Bucket delete error: {e}")

    async def kv_put(self, bucket_name: str, key: str, value: bytes):
        async with self.connection() as nc:
            try:
                kv = await nc.create_key_value(bucket=bucket_name)
                revision_number = await kv.put(key, value)
                entry = await kv.get(key)
                logger.debug(f"KeyValue: bucket={bucket_name}, key={entry.key}, revision_number={revision_number}")
                return revision_number
            except Exception as e:
                logger.error(f"Bucket {bucket_name} failed to add kv {key}. Error: {e}")

    async def kv_get(self, bucket_name, key: str):
        async with self.connection() as nc:
            try:
                kv = await nc.create_key_value(bucket=bucket_name)
                entry = await kv.get(key)
                return entry
            except Exception as e:
                logger.error(f"Bucket {bucket_name} failed to get record {key}. Error: {e}")

    async def kv_get_all(self, bucket_name):
        async with self.connection() as nc:
            try:
                kv = await nc.create_key_value(bucket=bucket_name)
                keys = await kv.keys()
                return keys
            except Exception as e:
                logger.error(f"Bucket {bucket_name} failed to get keys. Error: {e}")

    async def kv_delete(self, bucket_name, key: str):
        async with self.connection() as nc:
            try:
                kv = await nc.create_key_value(bucket=bucket_name)
                await kv.delete(key)
                logger.debug(f"Bucket {bucket_name} record {key} deleted")
            except Exception as e:
                logger.error(f"Bucket {bucket_name} failed to delete record {key}. Error: {e}")

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
