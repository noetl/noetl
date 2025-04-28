import os
from dataclasses import dataclass, field, asdict
from noetl.util import is_on, get_log_level

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
API_DIR = os.path.join(BASE_DIR, "api")
API_MODELS_DIR = os.path.join(API_DIR, "models")
API_ROUTES_DIR = os.path.join(API_DIR, "routes")
API_SCHEMAS_DIR = os.path.join(API_DIR, "schemas")
API_SERVICES_DIR = os.path.join(API_DIR, "services")
TMPL_DIR = os.path.join(API_DIR, "templates")
STATIC_DIR = os.path.join(API_DIR, "static")
APPCTX_DIR = os.path.join(BASE_DIR, "appctx")
CONFIG_DIR = os.path.join(BASE_DIR, "config")
CONNECTORS_DIR = os.path.join(BASE_DIR, "connectors")
DSL_DIR = os.path.join(BASE_DIR, "dsl")
PUBSUB_DIR = os.path.join(BASE_DIR, "pubsub")
RUNTIME_DIR = os.path.join(BASE_DIR, "runtime")
UTIL_DIR = os.path.join(BASE_DIR, "util")
WORKER_DIR = os.path.join(BASE_DIR, "worker")
CLI_DIR = os.path.join(BASE_DIR, "cli")


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
        return asdict(self)


@dataclass
class PostgresConfig:
    postgres_host: str = field(default_factory=lambda: os.getenv("POSTGRES_HOST", "localhost"))
    postgres_user: str = field(default_factory=lambda: os.getenv("POSTGRES_USER", "noetl"))
    postgres_password: str = field(default_factory=lambda: os.getenv("POSTGRES_PASSWORD", "noetl"))
    postgres_schema: str = field(default_factory=lambda: os.getenv("POSTGRES_SCHEMA", "public"))
    postgres_database: str = field(default_factory=lambda: os.getenv("POSTGRES_DATABASE", "noetl"))
    postgres_port: int = field(default_factory=lambda: int(os.getenv("POSTGRES_PORT", 5434)))
    postgres_pool_min_size: int = field(default_factory=lambda: int(os.getenv("POSTGRES_POOL_MIN_SIZE", 1)))
    postgres_pool_max_size: int = field(default_factory=lambda: int(os.getenv("POSTGRES_POOL_MAX_SIZE", 20)))
    postgres_pool_timeout: float = field(default_factory=lambda: float(os.getenv("POSTGRES_POOL_TIMEOUT", 1.0)))
    postgres_max_inactive_connection_lifetime: int = field(default_factory=lambda: int(os.getenv("POSTGRES_MAX_INACTIVE_CONNECTION_LIFETIME", 10)))
    postgres_server_settings: dict = field(default_factory=lambda: {"jit": "off"})
    timezone: str = field(default_factory=lambda: os.getenv("POSTGRES_TIMEZONE", "America/Chicago"))

    def connection_uri(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_database}"
        )

    def sqlalchemy_uri(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_database}"
        )


@dataclass
class AppConfig:
    base_dir: str = field(default_factory=lambda: os.getenv("BASE_DIR", BASE_DIR))
    api_dir: str = field(default_factory=lambda: API_DIR)
    templates_dir: str = field(default_factory=lambda: TMPL_DIR)
    static_dir: str = field(default_factory=lambda: STATIC_DIR)
    appctx_dir: str = field(default_factory=lambda: APPCTX_DIR)
    config_dir: str = field(default_factory=lambda: CONFIG_DIR)
    connectors_dir: str = field(default_factory=lambda: CONNECTORS_DIR)
    dsl_dir: str = field(default_factory=lambda: DSL_DIR)
    pubsub_dir: str = field(default_factory=lambda: PUBSUB_DIR)
    runtime_dir: str = field(default_factory=lambda: RUNTIME_DIR)
    util_dir: str = field(default_factory=lambda: UTIL_DIR)
    worker_dir: str = field(default_factory=lambda: WORKER_DIR)
    cli_dir: str = field(default_factory=lambda: CLI_DIR)
    data_dir: str = field(default_factory=lambda: os.getenv("DATA_DIR", BASE_DIR))
    cloud: CloudConfig = field(default_factory=CloudConfig)
    log: LogConfig = field(default_factory=LogConfig)
    postgres: PostgresConfig = field(default_factory=PostgresConfig)