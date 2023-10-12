import asyncio
import nats
from nats.aio.errors import ErrTimeout
from loguru import logger


class NatsConnectionPool:
    def __init__(self, url, size):
        self.connection_url = url
        self.size = size
        self.pool = asyncio.Queue()

    async def get(self):
        try:
            if self.pool.empty():
                nc = await nats.connect(self.connection_url)
                return nc
            else:
                return await self.pool.get()
        except ErrTimeout as e:
            logger.error(f"NATS connection timeout error: {e}")
            raise
        except Exception as e:
            logger.error(f"NATS connection error: {e}")
            raise

    def get_size(self):
        return self.size

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

    def connection(self):
        return self._ConnectionContextManager(self)


if __name__ == "__main__":
    nats_pool = NatsConnectionPool('nats://localhost:32645', 10)


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
