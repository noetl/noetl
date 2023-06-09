import os
from typing import Optional
from loguru import logger
from src.storage import read_yaml


class ConfigDict(dict):
    def __init__(self, *args, **kwargs):
        super(ConfigDict, self).__init__(*args, **kwargs)

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


class Config(ConfigDict):

    def __init__(self, *args, **kwargs):
        """
        Initializes the Config object with environment variables.
        :param config_path: Path to the dispatcher configuration file.
        :type config_path: Optional[str]
        """
        super().__init__(*args, **kwargs)
        self.log_level: str = os.getenv('LOG_LEVEL', 'info')
        self.config_path: Optional[str] = None

    def set_config_path(self, config_path: Optional[str] = None):
        """
        Sets the configuration path.
        :param config_path: path to the configuration file.
        :type config_path: Optional[str]
        """
        if config_path:
            self.config_path = config_path
        else:
            logger.error("Config path is empty")
