import os
from typing import Optional
from loguru import logger


class RedisConfig:
    """
    RedisConfig class for handling Redis configuration.
    """
    def __init__(self):
        self.redis_host: Optional[str] = os.getenv('REDIS_HOST', 'localhost')
        self.redis_port: str = str(os.getenv('REDIS_PORT', 6379))
        self.db: int = int(os.getenv('REDIS_DB', 0))
        self.key_ttl: int = int(os.getenv('REDIS_KEY_TTL', 10800))
        self.redis_socket_timeout: int = int(os.getenv('REDIS_SOCKET_TIMEOUT', 5))


class Config:
    """
    Config class for handling environment variables during startup.
    """
    workflow_config_path = None

    def __init__(self, config_path: Optional[str] = None):
        """
        Initializes the Config object with environment variables.
        :param config_path: Optional path to the workflow configuration file.
        :type config_path: Optional[str]
        """
        self.config_folder = str(os.getenv('CONFIG_DIR', '../../conf'))
        self.log_level: str = os.getenv('LOG_LEVEL', 'info')
        self.cloud_provider: str = str(os.getenv('CLOUD_PROVIDER', 'aws'))
        self.redis_config: RedisConfig = RedisConfig()
        self.workers: int = int(os.getenv('WORKERS', 5))
        self.retry: int = int(os.getenv('RETRY', 3))
        self.workflow_config_path: str = config_path
        self.print()

    def set_workflow_config_path(self, config_path: Optional[str] = None):
        """
        Sets the workflow configuration path.
        :param config_path: Optional path to the workflow configuration file.
        :type config_path: Optional[str]
        """
        if config_path:
            self.workflow_config_path: str = config_path
        else:
            logger.error("Config path is empty")

    def dict(self):
        return self.__dict__

    def __repr__(self):
        return '{%s}' % str(', '.join('%s : %s' % (k, repr(v)) for (k, v) in self.__dict__.items()))

    def print(self):
        logger.debug(self.__repr__())
