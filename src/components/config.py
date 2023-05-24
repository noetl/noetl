import os
from enum import Enum
from typing import Optional, Union, Any
from loguru import logger

from src.components import BaseRepr
from src.storage import read_yaml


class KindTemplate(dict):
    def __init__(self, *args, **kwargs):
        super(KindTemplate, self).__init__(*args, **kwargs)

    def get_keys(self) -> list:
        return list(self.keys())

    def get_value(self, path: str = None):
        try:
            value = self
            if path is None:
                return value
            keys = path.split(".")
            for key in keys:
                value = value.get(key)
                if value is None:
                    return None
            return value
        except Exception as e:
            logger.error(e)

    @classmethod
    async def create(cls, config_path):
        data = await read_yaml(config_path)
        return cls(data)


class Kind(Enum):
    """
    Enum class to represent the different kinds of entities.
    """
    DISPATCHER = "dispatcher"
    WORKFLOW = "workflow"
    JOB = "job"
    TASK = "task"
    ACTION = "action"


class Metadata(BaseRepr):
    """
    Metadata class to store information.
    """

    def __init__(self, name: str, kind: Kind):
        """
        Initializes a Metadata instance with the given name and kind.

        Args:
            name (str): The name of the entity.
            kind (Kind): The kind of the entity.
        """
        self.name: str = name
        self.kind: Kind = kind
        self.desc: Optional[str] = None


class Spec(BaseRepr):
    """
    Spec class to store specifications.
    """

    def __init__(self):
        """
        Initializes an empty Spec instance.
        """
        self.instance_id: Optional[str] = None
        self.schedule: Optional[str] = None
        self.runtime: Optional[Any] = None
        self.variables: Optional[dict] = None
        self.state: Optional[str] = None
        self.transitions: Optional[dict[str, list[str]]] = None
        self.conditions: Optional[list] = None


class RedisConfig(BaseRepr):
    """
    RedisConfig class for handling Redis configuration.
    """

    def __init__(self):
        self.redis_host: Optional[str] = os.getenv('REDIS_HOST', 'localhost')
        self.redis_port: str = str(os.getenv('REDIS_PORT', 6379))
        self.db: int = int(os.getenv('REDIS_DB', 0))
        self.key_ttl: int = int(os.getenv('REDIS_KEY_TTL', 10800))
        self.redis_socket_timeout: int = int(os.getenv('REDIS_SOCKET_TIMEOUT', 5))


class Config(BaseRepr):

    def __init__(self, config_path: Optional[str] = None):
        """
        Initializes the Config object with environment variables.
        :param config_path: Path to the dispatcher configuration file.
        :type config_path: Optional[str]
        """
        self.config_folder = str(os.getenv('CONFIG_DIR', '../conf'))
        self.log_level: str = os.getenv('LOG_LEVEL', 'info')
        self.redis_config: RedisConfig = RedisConfig()
        self.config_path: Optional[str] = config_path

    def set_config_path(self, config_path: Optional[str] = None):
        """
        Sets the dispatcher configuration path.
        :param config_path: Optional path to the workflow configuration file.
        :type config_path: Optional[str]
        """
        if config_path:
            self.config_path = config_path
        else:
            logger.error("Config path is empty")
