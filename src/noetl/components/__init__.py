import sys
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

import asyncio
from loguru import logger
from httpx import AsyncClient, Timeout, HTTPError

sys.path.append(str(Path(__file__).resolve().parent.parent))

"""
__init__.py: A collection of utility functions for the components package.
"""


class Kind(Enum):
    """
    Enum class to represent the different kinds of entities.
    """
    DISPATCHER = "dispatcher"
    WORKFLOW = "workflow"
    JOB = "job"
    TASK = "task"
    ACTION = "action"


class BaseRepr:
    def __repr__(self):
        return '{%s}' % str(', '.join('%s : %s' % (k, repr(v)) for (k, v) in self.__dict__.items()))

    def to_dict(self):
        return self.__dict__

    def print(self):
        logger.debug(self.__repr__())


def generate_instance_id(prefix: Optional[str] = None) -> str:
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
