from strawberry import UNSET, asdict
import yaml
from loguru import logger
import aiofiles
from typing import Any
from storage import RedisStorage

db = RedisStorage()


def to_dict(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items() if v != UNSET}
    elif isinstance(obj, list):
        return [to_dict(item) for item in obj]
    elif hasattr(obj, '__annotations__'):
        return to_dict(asdict(obj))
    else:
        return obj


async def read_yaml(path):
    async with aiofiles.open(path, "r") as f:
        yaml_config = await f.read()
        try:
            return yaml.safe_load(yaml_config)
        except yaml.YAMLError as e:
            logger.error(e)
