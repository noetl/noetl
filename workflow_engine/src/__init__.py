import asyncio
from typing import Callable, Any
import yaml
from loguru import logger
import aiofiles
import re
from httpx import AsyncClient, Timeout, HTTPError
import functools
import time

"""
__init__.py: A collection of utility functions for the workflow engine.
"""


def timer():
    """
    A decorator function that measures the execution time of the decorated function.
    :return: A wrapped version of the decorated function that includes timing logic.
    :rtype: Callable
    """

    def wrapper(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapped(*args, **kwargs) -> Any:
            start = time.time()
            try:
                return await func(*args, **kwargs)
            finally:
                end = time.time()
                total = end - start
                logger.info(f'Finished {func} in {total:.4f} seconds')

        return wrapped

    return wrapper
