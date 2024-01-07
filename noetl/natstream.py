import asyncio
import nats
from nats.js.api import StreamConfig, PubAck, RawStreamMsg
from nats.aio.msg import Msg
from nats.aio.errors import ErrTimeout
from dataclasses import dataclass, asdict
import json
from loguru import logger
from datetime import datetime
from uuid import uuid4


@dataclass
class NatsConfig:
    nats_url: str
    nats_pool_size: int


@dataclass
class NatsStreamReference:
    nats_msg_subject: str | None = None
    nats_msg_metadata: Msg.Metadata | None = None
    nats_msg_headers: dict | None = None
    nats_msg_reply: Msg.reply = None

    @property
    def __dict__(self):
        return self.to_dict()

    def to_dict(self):
        data = asdict(self)

        def convert_datetime(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            elif isinstance(obj, dict):
                return {k: convert_datetime(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_datetime(i) for i in obj]
            else:
                return obj

        return convert_datetime(data)

    def to_json(self):
        return json.dumps(self.to_dict())


class NatsConnectionPool:
    _instance = None

    def __new__(cls, config: NatsConfig | None):
        if cls._instance is None:
            cls._instance = super(NatsConnectionPool, cls).__new__(cls)
            cls._instance.config = config
            cls._instance.pool = asyncio.Queue()
        return cls._instance

    @classmethod
    def get_instance(cls, config: NatsConfig | None = None):
        if cls._instance is None:
            cls._instance = cls(config)
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

    async def publish(self, subject, message, stream) -> PubAck:
        async with self.connection() as js:
            ack: PubAck = await js.publish(subject=f"{subject}", payload=message, stream=stream)
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
        async with self.connection() as js:
            try:
                bucket = await js.create_key_value(bucket=bucket_name)
                logger.info(f"Bucket {bucket_name} created.")
                return bucket
            except Exception as e:
                print(f"Bucket create error: {e}")

    async def bucket_delete(self, bucket_name: str):
        async with self.connection() as js:
            try:
                bucket = await js.create_key_value(bucket_name)
                await bucket.delete(bucket_name)
                logger.info(f"Bucket {bucket_name} deleted.")
            except Exception as e:
                print(f"Bucket delete error: {e}")

    async def kv_put(self, bucket_name: str, key: str, value: bytes):
        async with self.connection() as js:
            try:
                kv = await js.create_key_value(bucket=bucket_name)
                revision_number = await kv.put(key, value)
                entry = await kv.get(key)
                logger.debug(f"KeyValue: bucket={bucket_name}, key={entry.key}, revision_number={revision_number}")
                return revision_number
            except Exception as e:
                logger.error(f"Bucket {bucket_name} failed to add kv {key}. Error: {e}")

    async def kv_get(self, bucket_name, key: str):
        async with self.connection() as js:
            try:
                kv = await js.create_key_value(bucket=bucket_name)
                entry = await kv.get(key)
                return entry.value
            except Exception as e:
                logger.error(f"Bucket {bucket_name} failed to get record {key}. Error: {e}")

    async def kv_get_all(self, bucket_name):
        async with self.connection() as js:
            try:
                kv = await js.create_key_value(bucket=bucket_name)
                keys = await kv.keys()
                return keys
            except Exception as e:
                logger.error(f"Bucket {bucket_name} failed to get keys. Error: {e}")

    async def kv_delete(self, bucket_name, key: str):
        async with self.connection() as js:
            try:
                kv = await js.create_key_value(bucket=bucket_name)
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


class NatsPool:
    nats_pool: NatsConnectionPool

    def __init__(self, nats_pool: NatsConnectionPool | NatsConfig = None):
        if nats_pool:
            self.initialize_nats_pool(nats_pool)

    def initialize_nats_pool(self, nats_pool: NatsConnectionPool | NatsConfig):
        if nats_pool is None:
            self.nats_pool = NatsConnectionPool.get_instance()
        elif isinstance(nats_pool, NatsConfig):
            self.nats_pool = NatsConnectionPool(config=nats_pool)
        elif isinstance(nats_pool, NatsConnectionPool):
            self.nats_pool = nats_pool
        else:
            raise TypeError("nats_pool must be type of NatsConnectionPool or NatsConfig")

    async def get_nats_pool(self):
        if self.nats_pool is None:
            raise ValueError("NatsPool is not initialized")
        else:
            return self.nats_pool

    async def get_msg(self, stream, sequence):
        async with self.nats_pool.connection() as js:
            try:
                msg = await js.get_msg(stream, sequence)
                return msg
            except Exception as e:
                logger.error(f"JetStream get message error for stream {stream} sequence {sequence}: {e}")
                raise

    async def nats_read_subject(self, subject: str):
        msg_data = None
        if self.nats_pool is None:
            await self.get_nats_pool()

        async def message_handler(msg):
            nonlocal msg_data
            msg_data = msg.data

        try:
            async with self.nats_pool.connection() as js:
                _ = await js.subscribe(
                    subject=f"{subject}",
                    durable=str(uuid4()),
                    cb=message_handler,
                )
                await asyncio.sleep(0.01)
            return msg_data

        except ErrTimeout:
            logger.error(f"NATS subject {subject} read timeout error.")
        except Exception as e:
            logger.info(f"NATS subject {subject} read error {e}.")

    async def nats_read(self, subject: str, stream: str, queue: str, cb):
        async with self.nats_pool.connection() as js:
            await js.subscribe(subject=subject, stream=stream, cb=cb, queue=queue)
            while True:
                await asyncio.sleep(1)

    async def nats_write(self, subject: str, stream: str, payload: bytes):
        async with self.nats_pool.connection() as js:
            return await js.publish(subject=subject, stream=stream, payload=payload)


if __name__ == "__main__":
    nats_config: NatsConfig = NatsConfig(nats_url="nats://localhost:32222", nats_pool_size=10)
    nats_pool = NatsConnectionPool(config=nats_config)


    async def test():
        async def func(js):
            ack: PubAck = await js.publish('test.greeting', b'Hello JS!')
            logger.info(f'Ack: stream={ack.stream}, sequence={ack.seq}')

        return await nats_pool.execute(func)


    async def _main():
        result = await test()
        print(result)
        await nats_pool.close_pool()


    asyncio.run(_main())
