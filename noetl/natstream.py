import asyncio
from nats.js import JetStreamManager
from nats.aio.client import Client as NATS
from nats.errors import ConnectionClosedError, TimeoutError
from loguru import logger

class NatsConnectionPool:
    def __init__(self, url ,size):
        self.connection_url = url
        self.size = size
        self.pool = asyncio.Queue()

    async def get(self):
        if self.pool.empty():
            nc = NATS()
            await nc.connect(self.connection_url)
            return nc
        else:
            return await self.pool.get()

    async def put(self, nc):
        await self.pool.put(nc)

    async def execute(self, func):
        nc = await self.get()
        try:
            js = nc.JetStreamManager(nc)
            return await func(js)
        finally:
            await self.put(nc)
