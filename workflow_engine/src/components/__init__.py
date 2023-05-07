import sys
from pathlib import Path
import asyncio
from loguru import logger
from httpx import AsyncClient, Timeout, HTTPError

sys.path.append(str(Path(__file__).resolve().parent.parent))

"""
__init__.py: A collection of utility functions for the components package.
"""


async def http_get_request(url):
    """
    Performs an asynchronous HTTP GET request to the specified URL with retries and error handling.
    :param url: The URL to send the request to.
    :type url: str
    :return: The response object containing the result of the request.
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
