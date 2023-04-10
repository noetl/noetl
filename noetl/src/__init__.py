import asyncio
from loguru import logger
import functools
import time
from typing import Callable, Any, Optional, Union, AnyStr
import yaml


def read_yaml(path: AnyStr):
    with open(path, 'r') as stream:
        try:
            return yaml.safe_load(stream)
        except yaml.YAMLError as e:
            logger.error(e)


def set_event_loop(event_loop, obj_iter):
    for obj in obj_iter:
        obj.set_event_loop(event_loop)


async def task_exception(task):
    try:
        await task
    except Exception as e:
        logger.error(e)


def diff_minutes_seconds(dt_from, dt_to) -> (int, int):
    minutes, seconds = divmod((dt_from.now() - dt_to).total_seconds(), 60)
    return minutes, seconds


def async_timer():
    def wrapper(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            start = time.time()
            try:
                return await func(*args, **kwargs)
            finally:
                finish = time.time()
                logger.info(f'finished {func} in {finish - start:.4f} seconds')

        return wrapper

    return wrapper
