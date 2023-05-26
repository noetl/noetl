import os
from typing import Optional
from loguru import logger
from src.components.models.template import DictTemplate


class Config(DictTemplate):

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
