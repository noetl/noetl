import os

from redis import asyncio as aioredis
from typing import Any, Optional, Union
from loguru import logger
from src.storage.base_storage import BaseStorage


class RedisStorage(BaseStorage):
    """
    RedisStorage class for handling Redis database operations.
    """

    def __init__(self):
        self.host: str = os.getenv('REDIS_HOST', 'localhost')
        self.port: str = str(os.getenv('REDIS_PORT', 6379))
        self.db: int = int(os.getenv('REDIS_DB', 0))
        self.key_ttl: int = int(os.getenv('REDIS_KEY_TTL', 10800))
        self.socket_timeout = int(os.getenv('REDIS_SOCKET_TIMEOUT', 5))
        self.client: Optional[Any] = None

    async def save(self, key: str, value: Union[str, Any]):
        await self.pool_connect()
        if isinstance(key, str) and isinstance(value, str):
            await self.set(key, value)
        else:
            await self.hset(key, value)

    async def load(self, key):
        await self.pool_connect()
        return await self.get(key)

    def get_redis_url(self):
        """
        Constructs the Redis connection URL.
        :return: Redis connection URL
        :rtype: str
        """
        return f"redis://{self.host}:{self.port}/{self.db}"

    async def get_redis_pool(self):
        """
        Initializes a Redis connection pool.
        """
        pool = aioredis.ConnectionPool.from_url(
            url=self.get_redis_url(),
            decode_responses=True
        )
        self.client = aioredis.Redis(connection_pool=pool)

    async def pool_connected(self):
        """
        Checks if the connection pool is connected to Redis.
        :return: True if connected, False otherwise
        :rtype: bool
        """
        if self.client:
            ping_result = await self.client.ping()
            return ping_result
        return False

    async def pool_connect(self):
        """
        Connects to Redis using a connection pool if not already connected.
        """
        try:
            if not await self.pool_connected():
                await self.get_redis_pool()
        except Exception as e:
            logger.error(f'RadisHandler error {e}')

    async def connect(self):
        """
        Connects to Redis.
        """
        self.client = await aioredis.from_url(self.get_redis_url())

    async def disconnect(self):
        """
        Disconnects from Redis.
        """
        await self.client.close()

    async def key_exists(self, key):
        """
        Checks if the given key exists in Redis.
        :param key: Key to check
        :type key: str
        :return: True if the key exists, False otherwise
        :rtype: bool
        """
        if await self.client.exists(key) == 0:
            return False
        return True

    async def set(self, key: str, value: Any):
        """
        Sets a key-value pair in Redis.
        :param key: Key to set
        :type key: str
        :param value: Value to set
        :type value: Any
        """
        try:
            await self.client.set(key, value)
        except Exception as e:
            logger.error(f'Redis set error {e}')

    async def get(self, key) -> Any:
        """
        Retrieves the value associated with the given key from Redis.
        :param key: Key to get
        :type key: str
        :return: Value associated with the key
        :rtype: Any
        """
        try:
            value = await self.client.get(key)
            return value
        except Exception as e:
            logger.error(f'Redis get error {e}')

    async def hget(self, key, fields):
        """
        Retrieves the specified fields from a hash stored at the given key in Redis.
        :param key: Key of the hash
        :type key: str
        :param fields: List of fields to retrieve
        :type fields: list
        :return: The values of the specified fields in the hash
        :rtype: list
        """
        try:
            redis_result = await self.client.hget(key, *fields)
            return redis_result
        except Exception as e:
            logger.error(f'Redis hget error {e}')


    async def hset(self, key, payload, ttl=None):
        """
        Sets the specified payload (key-value pairs) in a hash stored at the given key in Redis.
        :param key: Key of the hash
        :type key: str
        :param payload: Key-value pairs to set
        :type payload: dict
        :param ttl: Time-to-live for the key, optional
        :type ttl: int, optional
        """
        try:
            logger.info(payload)
            await self.client.hset(key, mapping=payload)
            if ttl:
                await self.client.expire(key, ttl)
        except Exception as e:
            logger.error(f'Redis hash set key: {key} payload: {payload} error {e}')


    async def hgetall(self, key):
        """
        Retrieves all fields and values of a hash stored at the given key in Redis.
        :param key: Key of the hash
        :type key: str
        :return: All fields and values of the hash
        :rtype: dict
        """
        try:
            redis_result = await self.client.hgetall(key)
            return redis_result
        except Exception as e:
            logger.error(f'Redis hash get all error {e}')


async def get_state_key(self, workflow_name: str, workflow_instance_id: str, job_name: str, task_name: str) -> str:
    """
    Constructs a state key for the given workflow, instance, job, and task names.
    :param workflow_name: Name of the workflow
    :type workflow_name: str
    :param workflow_instance_id: ID of the workflow instance
    :type workflow_instance_id: str
    :param job_name: Name of the job
    :type job_name: str
    :param task_name: Name of the task
    :type task_name: str
    :return: State key
    :rtype: str
    """
    return f"/workflow_state_db/{workflow_name}/{workflow_instance_id}/jobs/{job_name}/tasks/{task_name}"
