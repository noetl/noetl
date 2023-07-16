import yaml
from loguru import logger
import aiofiles
from datetime import datetime
from httpx import AsyncClient, Timeout, HTTPError
import asyncio


async def read_yaml(path):
    async with aiofiles.open(path, "r") as f:
        yaml_config = await f.read()
        try:
            return yaml.safe_load(yaml_config)
        except yaml.YAMLError as e:
            logger.error(e)


class BaseRepr:
    def __repr__(self):
        return '{%s}' % str(', '.join('%s : %s' % (k, repr(v)) for (k, v) in self.__dict__.items()))

    def to_dict(self):
        return self.__dict__

    def print(self):
        logger.debug(self.__repr__())


def generate_instance_id(prefix: None | str = None) -> str:
    """
    Generate a unique instance ID based on the workflow name and the current timestamp.
    The generated ID will have the format "name-YYYYmmddTHHMMSSZ" naturally ordered.
    :param prefix:
    :param name: The name of the dispatcher or workflow.
    :type name: str
    """
    now = datetime.utcnow()
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    if prefix is None:
        return timestamp
    instance_id = f"{prefix}-{timestamp}"
    logger.debug(instance_id)
    return instance_id


async def http_get_request(url):
    """
    Performs an asynchronous HTTP GET request to the specified URL with retries and error handling.
    :param url: The URL to send the request to.
    :type url: str
    :return: Result of the request.
    :rtype: httpx.Response
    """
    timeout, response, url, retry = Timeout(30.0, connect=60.0), None, f'http://{url}' if 'http' not in url else url, 3
    try:
        while retry > 0:
            async with AsyncClient() as client:
                response = await client.get(url, timeout=timeout)
            response.raise_for_status()
            if response:
                return response
            else:
                retry -= 1
                await asyncio.sleep(10)
        return response
    except HTTPError as e:
        logger.error(f"Error while requesting url {e.request.url}.")
        async with AsyncClient() as client:
            return await client.get(url, timeout=timeout)
    except Exception as e:
        logger.error(f'{e}')
