import os
from dataclasses import dataclass, field, asdict
from noetl.shared.utils import is_on, get_log_level
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__)))
TMPL_DIR = os.path.join(BASE_DIR, "templates")

@dataclass
class CloudConfig:
    google_project: str = field(default_factory=lambda: os.getenv("GOOGLE_PROJECT", "noetl"))
    google_region: str = field(default_factory=lambda: os.getenv("GOOGLE_REGION", "us-central1"))

@dataclass
class LogConfig:
    app_name: str = field(default_factory=lambda: os.getenv("APP_NAME", "noetl"))
    log_level: int = field(default_factory=lambda: get_log_level())
    workflow_log_level: str = field(default_factory=lambda: os.getenv("WORKFLOW_LOG_LEVEL", "LOG_NONE"))
    queue_size: int = field(default_factory=lambda: int(os.getenv("LOG_QUEUE_SIZE", 1000)))
    service_name: str = field(default_factory=lambda: os.getenv("SERVICE_NAME", os.getenv("APP_NAME", "noetl")))
    google_logging: bool = field(default_factory=lambda: is_on(os.getenv("GOOGLE_LOGGING", "false")))
    database_logging: bool = field(default_factory=lambda: is_on(os.getenv("DATABASE_LOGGING", "true")))
    log_threading: bool = field(default_factory=lambda: is_on(os.getenv("LOG_THREADING", "false")))
    capture_context: bool = field(default_factory=lambda: is_on(os.getenv("LOG_CAPTURE_CONTEXT", "false")))
    def as_dict(self):
        asdict(self)

@dataclass
class PostgresConfig:
    postgres_host: str = field(default_factory=lambda: os.getenv("POSTGRES_HOST", "localhost"))
    postgres_user: str = field(default_factory=lambda: os.getenv("POSTGRES_USER", "noetl"))
    postgres_password: str = field(default_factory=lambda: os.getenv("POSTGRES_PASSWORD", "noetl"))
    postgres_schema: str = field(default_factory=lambda: os.getenv("POSTGRES_SCHEMA", "public"))
    postgres_database: str = field(default_factory=lambda: os.getenv("POSTGRES_DATABASE", "noetl"))
    postgres_port: int = field(default_factory=lambda: int(os.getenv("POSTGRES_PORT", 5434)))
    postgres_pool_min_size: int = field(default_factory=lambda: int(os.getenv("POSTGRES_POOL_MIN_SIZE", 1)))
    postgres_pool_max_size: int = field(default_factory=lambda: int(os.getenv("POSTGRES_POOL_MAX_SIZE", 100)))
    postgres_pool_timeout: float = field(default_factory=lambda: int(os.getenv("POSTGRES_POOL_TIMEOUT", 1.0)))
    postgres_max_inactive_connection_lifetime: int = field(default_factory= lambda: int(os.getenv("POSTGRES_MAX_INACTIVE_CONNECTION_LIFETIME", 10)))
    postgres_server_settings={'jit': 'off'}
    timezone: str = field(default_factory=lambda: os.getenv("POSTGRES_TIMEZONE", "America/Chicago"))

@dataclass
class AppConfig:
    cloud: CloudConfig = field(default_factory=CloudConfig)
    base_dir: str = field(default_factory=lambda: os.getenv("BASE_DIR", BASE_DIR))
    data_dir: str = field(default_factory=lambda: os.getenv("DATA_DIR", BASE_DIR))
    templates_directory: str = TMPL_DIR
    log: LogConfig = field(default_factory=LogConfig)
    postgres: PostgresConfig = field(default_factory=PostgresConfig)
