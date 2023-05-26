import sys
from pathlib import Path
import yaml
from loguru import logger
import aiofiles

from src.storage.redis_storage import RedisStorage

sys.path.append(str(Path(__file__).resolve().parent.parent))

db = RedisStorage()


async def read_yaml(path):
    """
    Asynchronously reads a YAML file and returns a dictionary representing the contents of the file.
    :param path: The path to the YAML file.
    :type path: str
    :return: A dictionary representing the contents of the YAML file.
    :rtype: dict
    """
    async with aiofiles.open(path, "r") as f:
        yaml_config = await f.read()
        try:
            return yaml.safe_load(yaml_config)
        except yaml.YAMLError as e:
            logger.error(e)
