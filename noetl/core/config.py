import os
import sys
import socket
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, ConfigDict, model_validator, field_validator
from pathlib import Path


_ENV_LOADED = False

def _load_env_file(path: str, allow_override: bool = False) -> None:
    """
    Minimal .env loader: loads KEY=VALUE pairs into os.environ.
    - Ignores empty lines and lines starting with '#'
    - Supports values wrapped in single or double quotes
    - By default, does not override existing environment variables
    - Set allow_override=True to override existing variables
    """
    try:
        if not path or not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].strip()
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                if allow_override or key not in os.environ:
                    os.environ[key] = value
    except FileNotFoundError:
        # Silent pass for missing .env files - this is expected
        pass
    except PermissionError as e:
        print(f"FATAL: Permission denied reading environment file {path}: {e}", file=sys.stderr)
        raise
    except Exception as e:
        print(f"FATAL: Failed to load environment file {path}: {e}", file=sys.stderr)
        raise

def load_env_if_present(force_reload: bool = False) -> None:
    """
    Load environment variables from .env files in order of precedence:
    1. .env.local (highest priority, not committed)
    2. .env.{ENVIRONMENT} (environment-specific)
    3. .env.common (common variables)
    4. .env (default)
    Only loads when NOETL_ENV_FILE is provided or when loading defaults.
    """
    global _ENV_LOADED
    if _ENV_LOADED and not force_reload:
        return
    
    custom = os.environ.get("NOETL_ENV_FILE")
    if custom:
        _load_env_file(custom, allow_override=False)
    else:
        # Load default .env files in order of precedence
        env_files = ['.env.local', '.env.common', '.env']
        environment = os.environ.get('ENVIRONMENT', '').strip()
        if environment:
            env_files.insert(1, f'.env.{environment}')
        
        for env_file in env_files:
            _load_env_file(env_file, allow_override=False)
    
    if not force_reload:
        _ENV_LOADED = True

def validate_mandatory_env_vars():
    """
    Validate that all mandatory environment variables are present and not empty.
    Exit immediately if any are missing.
    """
    mandatory_vars = [
        # Admin DB
        'POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB', 'POSTGRES_HOST', 'POSTGRES_PORT',
        # NoETL principal
        'NOETL_USER', 'NOETL_PASSWORD', 'NOETL_SCHEMA',
        # Runtime config
        'NOETL_HOST', 'NOETL_PORT', 'NOETL_ENABLE_UI', 'NOETL_DEBUG',
        # Server identity
        'NOETL_SERVER_URL', 'NOETL_SERVER_NAME',
        # Server runtime
        'NOETL_SERVER', 'NOETL_SERVER_WORKERS', 'NOETL_SERVER_RELOAD',
        # Server runtime tuning (required)
        'NOETL_AUTO_RECREATE_RUNTIME', 'NOETL_HEARTBEAT_RETRY_AFTER',
        'NOETL_RUNTIME_SWEEP_INTERVAL', 'NOETL_RUNTIME_OFFLINE_SECONDS',
        'NOETL_DISABLE_METRICS', 'NOETL_SERVER_METRICS_INTERVAL',
        # Drop schema control
        'NOETL_DROP_SCHEMA'
    ]

    missing_vars = []
    empty_vars = []

    for var in mandatory_vars:
        if var not in os.environ:
            missing_vars.append(var)
        elif not os.environ[var] or not os.environ[var].strip():
            empty_vars.append(var)

    if missing_vars or empty_vars:
        error_msg = []
        if missing_vars:
            error_msg.append(f"Missing environment variables: {', '.join(missing_vars)}")
        if empty_vars:
            error_msg.append(f"Empty environment variables: {', '.join(empty_vars)}")

        print(f"FATAL: {' | '.join(error_msg)}", file=sys.stderr)
        print("FATAL: Missing required environment variables for server start", file=sys.stderr)
        print("FATAL: Required variables:", file=sys.stderr)
        for var in mandatory_vars:
            value = os.environ.get(var, '<MISSING>')
            if value and value.strip():
                if 'PASSWORD' in var:
                    masked_value = '*' * len(value)
                    print(f"  {var}={masked_value}", file=sys.stderr)
                else:
                    print(f"  {var}={value}", file=sys.stderr)
            else:
                print(f"  {var}=<MISSING OR EMPTY>", file=sys.stderr)

        sys.exit(1)

    print("All mandatory environment variables validated successfully")

class Settings(BaseModel):
    """
    NoETL application settings from environment variables.
    """
    model_config = ConfigDict(validate_assignment=True)

    raw_env: Dict[str, str] = Field(default_factory=dict, exclude=True)

    app_name: str = "NoETL"
    app_version: str = "0.1.39"

    # Runtime configuration (required; no defaults)
    host: str = Field(..., alias="NOETL_HOST")
    port: int = Field(..., alias="NOETL_PORT")
    enable_ui: bool = Field(..., alias="NOETL_ENABLE_UI")
    debug: bool = Field(..., alias="NOETL_DEBUG")

    # Database configuration (required)
    postgres_user: str = Field(..., alias="POSTGRES_USER")
    postgres_password: str = Field(..., alias="POSTGRES_PASSWORD") 
    postgres_db: str = Field(..., alias="POSTGRES_DB")
    postgres_host: str = Field(..., alias="POSTGRES_HOST")
    postgres_port: str = Field(..., alias="POSTGRES_PORT")

    # NoETL-specific DB principal (required)
    noetl_user: str = Field(..., alias="NOETL_USER")
    noetl_password: str = Field(..., alias="NOETL_PASSWORD")
    noetl_schema: str = Field(..., alias="NOETL_SCHEMA")

    # Drop schema flag (required; admin will drop schema when true)
    noetl_drop_schema: bool = Field(..., alias="NOETL_DROP_SCHEMA")

    # Schema validation / ensure flag (renamed from NOETL_SCHEMA_ENSURE)
    schema_validate: bool = Field(..., alias="NOETL_SCHEMA_VALIDATE")

    # NATS Configuration
    nats_url: str = Field(default="nats://noetl:noetl@localhost:30422", alias="NATS_URL")
    nats_user: str = Field(default="noetl", alias="NATS_USER")
    nats_password: str = Field(default="noetl", alias="NATS_PASSWORD")
    nats_stream: str = Field(default="NOETL_COMMANDS", alias="NATS_STREAM")
    nats_consumer: str = Field(default="noetl_worker_pool", alias="NATS_CONSUMER")
    nats_subject: str = Field(default="noetl.commands", alias="NATS_SUBJECT")

    # Keychain configuration
    keychain_refresh_threshold: int = Field(default=300, alias="NOETL_KEYCHAIN_REFRESH_THRESHOLD")  # seconds (5min default)

    # Server identity and base URL (required)
    server_url: str = Field(..., alias="NOETL_SERVER_URL")
    server_name: str = Field(..., alias="NOETL_SERVER_NAME")

    # Server runtime (required; no defaults)
    server_runtime: str = Field(..., alias="NOETL_SERVER")            # "uvicorn" | "gunicorn" | "auto"
    server_workers: int = Field(..., alias="NOETL_SERVER_WORKERS")    # >= 1
    server_reload: bool = Field(..., alias="NOETL_SERVER_RELOAD")     # true/false
    auto_recreate_runtime: bool = Field(..., alias="NOETL_AUTO_RECREATE_RUNTIME")
    heartbeat_retry_after: int = Field(..., alias="NOETL_HEARTBEAT_RETRY_AFTER")
    runtime_sweep_interval: float = Field(..., alias="NOETL_RUNTIME_SWEEP_INTERVAL")
    runtime_offline_seconds: int = Field(..., alias="NOETL_RUNTIME_OFFLINE_SECONDS")
    disable_metrics: bool = Field(..., alias="NOETL_DISABLE_METRICS")
    server_metrics_interval: float = Field(..., alias="NOETL_SERVER_METRICS_INTERVAL")
    server_labels_raw: Optional[str] = Field(None, alias="NOETL_SERVER_LABELS")
    hostname_env: Optional[str] = Field(None, alias="HOSTNAME")

    @field_validator('postgres_user', 'postgres_password', 'postgres_db', 'postgres_host',
                     'postgres_port', 'noetl_user', 'noetl_password', 'noetl_schema', 'host', 'server_runtime', 'server_url', 'server_name', mode='before')
    def validate_not_empty_str(cls, v):
        if not isinstance(v, str) or not v.strip():
            raise ValueError("Value cannot be empty or whitespace only")
        return v.strip()

    @field_validator(
        'enable_ui',
        'debug',
        'noetl_drop_schema',
        'server_reload',
        'auto_recreate_runtime',
        'disable_metrics',
        mode='before'
    )
    def coerce_bool(cls, v):
        if isinstance(v, bool):
            return v
        if not isinstance(v, str):
            raise ValueError("Expected string for boolean field")
        val = v.strip().lower()
        if val in ("true", "1", "yes", "y", "on"):
            return True
        if val in ("false", "0", "no", "n", "off"):
            return False
        raise ValueError(f"Invalid boolean value: {v}")

    @field_validator('runtime_sweep_interval', 'server_metrics_interval', mode='before')
    def coerce_float(cls, v):
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            return float(v.strip())
        raise ValueError("Expected float-compatible value")

    @field_validator('runtime_offline_seconds', 'heartbeat_retry_after', 'server_workers', mode='before')
    def coerce_int(cls, v):
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            return int(v.strip())
        raise ValueError("Expected integer-compatible value")

    @model_validator(mode='after')
    def validate_database_config(self):
        """Database and server configuration validation"""
        try:
            port = int(self.postgres_port)
            if port < 1 or port > 65535:
                raise ValueError(f"Invalid port number: {port}")
        except ValueError as e:
            print(f"FATAL: Invalid POSTGRES_PORT value '{self.postgres_port}': {e}", file=sys.stderr)
            sys.exit(1)

        try:
            if self.port < 1 or self.port > 65535:
                raise ValueError(f"Invalid NOETL_PORT number: {self.port}")
        except Exception as e:
            print(f"FATAL: Invalid NOETL_PORT value '{self.port}': {e}", file=sys.stderr)
            sys.exit(1)

        try:
            if int(self.server_workers) < 1:
                raise ValueError("NOETL_SERVER_WORKERS must be >= 1")
        except Exception as e:
            print(f"FATAL: Invalid NOETL_SERVER_WORKERS value '{self.server_workers}': {e}", file=sys.stderr)
            sys.exit(1)

        valid_runtimes = {"uvicorn", "gunicorn", "auto"}
        if self.server_runtime not in valid_runtimes:
            print(f"FATAL: Invalid NOETL_SERVER value '{self.server_runtime}'. Expected one of {sorted(valid_runtimes)}", file=sys.stderr)
            sys.exit(1)

        return self

    @property
    def hostname(self) -> str:
        if self.hostname_env and self.hostname_env.strip():
            return self.hostname_env.strip()
        return socket.gethostname()

    @property
    def server_labels(self) -> List[str]:
        if not self.server_labels_raw:
            return []
        return [label.strip() for label in self.server_labels_raw.split(',') if label.strip()]

    @property
    def server_api_url(self) -> str:
        url = self.server_url.rstrip('/')
        if not url.endswith('/api'):
            url = f"{url}/api"
        return url

    @property
    def admin_conn_string(self) -> str:
        """Get admin connection string for database operations"""
        return f"dbname={self.postgres_db} user={self.postgres_user} password={self.postgres_password} host={self.postgres_host} port={self.postgres_port}"

    @property
    def noetl_conn_string(self) -> str:
        """Get NoETL user connection string"""
        return f"dbname={self.postgres_db} user={self.noetl_user} password={self.noetl_password} host={self.postgres_host} port={self.postgres_port}"

    @property
    def ui_build_path(self) -> Path:
        """
        Path to built UI assets inside the package (noetl/ui/build).
        Derived from the package location to avoid hard-coded paths.
        """
        return (Path(__file__).resolve().parent / "ui")

    @property
    def favicon_file(self) -> Path:
        """
        Path to UI favicon file within the built assets directory.
        """
        return self.ui_build_path / "favicon.ico"

    @property
    def pid_file_dir(self) -> str:
        """
        Directory for storing server PID file.
        """
        return os.path.expanduser("~/.noetl")

    @property
    def pid_file_path(self) -> str:
        """
        Full path to server PID file.
        """
        return os.path.join(self.pid_file_dir, "noetl_server.pid")

    # API Endpoint URLs - centralized endpoint construction
    @property
    def endpoint_runtime_register(self) -> str:
        """Runtime registration endpoint"""
        return f"{self.server_api_url}/runtime/register"

    @property
    def endpoint_runtime_deregister(self) -> str:
        """Runtime deregistration endpoint"""
        return f"{self.server_api_url}/runtime/deregister"

    @property
    def endpoint_events(self) -> str:
        """Events submission endpoint"""
        return f"{self.server_api_url}/events"

    @property
    def endpoint_credentials(self) -> str:
        """Base credentials endpoint"""
        return f"{self.server_api_url}/credentials"

    def endpoint_credential_by_key(self, key: str, include_data: bool = True) -> str:
        """Get credential by key endpoint with optional data inclusion"""
        url = f"{self.endpoint_credentials}/{key}"
        if include_data:
            url += "?include_data=true"
        return url

_settings: Optional[Settings] = None
class WorkerSettings(BaseModel):
    """Worker runtime configuration derived from environment variables."""
    model_config = ConfigDict(validate_assignment=True)

    raw_env: Dict[str, str] = Field(default_factory=dict, exclude=True)

    pool_runtime: str = Field("cpu", alias="NOETL_WORKER_POOL_RUNTIME")
    pool_name: Optional[str] = Field(None, alias="NOETL_WORKER_POOL_NAME")
    server_url: str = Field("http://localhost:8082", alias="NOETL_SERVER_URL")
    worker_base_url: str = Field("http://queue-worker", alias="NOETL_WORKER_BASE_URL")
    worker_capacity_raw: Optional[str] = Field(None, alias="NOETL_WORKER_CAPACITY")
    worker_labels_raw: Optional[str] = Field(None, alias="NOETL_WORKER_LABELS")
    namespace: Optional[str] = Field(None, alias="POD_NAMESPACE")
    worker_id: Optional[str] = Field(None, alias="NOETL_WORKER_ID")
    deregister_retries: int = Field(3, alias="NOETL_DEREGISTER_RETRIES")
    deregister_backoff: float = Field(0.5, alias="NOETL_DEREGISTER_BACKOFF")
    metrics_disabled: bool = Field(True, alias="NOETL_DISABLE_METRICS")
    worker_metrics_interval: float = Field(60.0, alias="NOETL_WORKER_METRICS_INTERVAL")
    worker_heartbeat_interval: float = Field(15.0, alias="NOETL_WORKER_HEARTBEAT_INTERVAL")
    hostname_env: Optional[str] = Field(None, alias="HOSTNAME")
    host: str = Field("localhost", alias="NOETL_HOST")
    port: str = Field("8082", alias="NOETL_PORT")
    server_name: Optional[str] = Field(None, alias="NOETL_SERVER_NAME")
    max_workers: int = Field(8, alias="NOETL_MAX_WORKERS")

    @field_validator('pool_runtime', mode='before')
    def normalize_runtime(cls, v):
        if v is None:
            return "cpu"
        return str(v).strip().lower()

    @field_validator('metrics_disabled', mode='before')
    def coerce_bool(cls, v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            val = v.strip().lower()
            if val in {"true", "1", "yes", "y", "on"}:
                return True
            if val in {"false", "0", "no", "n", "off"}:
                return False
        raise ValueError("Invalid boolean value")

    @field_validator(
        'deregister_retries',
        'max_workers',
        'deregister_backoff',
        'worker_metrics_interval',
        'worker_heartbeat_interval',
        mode='before'
    )
    def coerce_numeric(cls, v, info):
        target = info.field_name
        if target in {'deregister_retries', 'max_workers'}:
            if isinstance(v, int):
                return v
            if isinstance(v, str):
                return int(v.strip())
            if isinstance(v, float):
                return int(v)
            raise ValueError("Invalid integer value")
        # float targets
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            return float(v.strip())
        raise ValueError("Invalid numeric value")

    @property
    def hostname(self) -> str:
        if self.hostname_env and self.hostname_env.strip():
            return self.hostname_env.strip()
        return socket.gethostname()

    @property
    def worker_capacity(self) -> Optional[int]:
        if not self.worker_capacity_raw:
            return None
        try:
            return int(str(self.worker_capacity_raw).strip())
        except (TypeError, ValueError):
            raise ValueError(f"Invalid NOETL_WORKER_CAPACITY value: {self.worker_capacity_raw}")

    @property
    def worker_labels(self) -> List[str]:
        if not self.worker_labels_raw:
            return []
        return [label.strip() for label in self.worker_labels_raw.split(',') if label.strip()]

    @property
    def resolved_pool_name(self) -> str:
        if self.pool_name and self.pool_name.strip():
            return self.pool_name.strip()
        return f"worker-{self.pool_runtime}"

    @property
    def server_api_url(self) -> str:
        url = self.server_url.rstrip('/')
        if not url.endswith('/api'):
            url = f"{url}/api"
        return url

    @property
    def normalized_server_url(self) -> str:
        url = self.server_url.strip()
        if not url.startswith(("http://", "https://")):
            url = f"http://{url}"
        return url.rstrip('/')

    # Worker API Endpoint URLs - centralized endpoint construction
    @property
    def endpoint_worker_pool_register(self) -> str:
        """Worker pool registration endpoint"""
        return f"{self.server_api_url}/worker/pool/register"

    @property
    def endpoint_worker_pool_deregister(self) -> str:
        """Worker pool deregistration endpoint"""
        return f"{self.server_api_url}/worker/pool/deregister"

    @property
    def endpoint_worker_pool_heartbeat(self) -> str:
        """Worker pool heartbeat endpoint"""
        return f"{self.server_api_url}/worker/pool/heartbeat"

    @property
    def endpoint_queue_lease(self) -> str:
        """Queue job lease endpoint"""
        return f"{self.server_api_url}/queue/lease"

    @property
    def endpoint_queue_complete(self) -> str:
        """Queue job completion endpoint"""
        return f"{self.server_api_url}/queue/complete"

    def endpoint_queue_complete_by_id(self, queue_id: int) -> str:
        """Queue job completion endpoint by queue ID"""
        return f"{self.server_api_url}/queue/{queue_id}/complete"

    @property
    def endpoint_queue_fail(self) -> str:
        """Queue job failure endpoint"""
        return f"{self.server_api_url}/queue/fail"

    def endpoint_queue_fail_by_id(self, queue_id: int) -> str:
        """Queue job failure endpoint by queue ID"""
        return f"{self.server_api_url}/queue/{queue_id}/fail"

    @property
    def endpoint_queue_size(self) -> str:
        """Queue size endpoint"""
        return f"{self.server_api_url}/queue/size"

    @property
    def endpoint_events(self) -> str:
        """Events submission endpoint"""
        return f"{self.server_api_url}/events"

    @property
    def endpoint_credentials(self) -> str:
        """Base credentials endpoint"""
        return f"{self.server_api_url}/credentials"

    def endpoint_credential_by_key(self, key: str, include_data: bool = True) -> str:
        """Get credential by key endpoint with optional data inclusion"""
        url = f"{self.endpoint_credentials}/{key}"
        if include_data:
            url += "?include_data=true"
        return url


_settings: Optional[Settings] = None
_worker_settings: Optional[WorkerSettings] = None

def get_settings(reload: bool = False) -> Settings:
    """
    Get application settings. Validates environment variables on first call.
    Set reload=True to force reloading from current environment.
    """
    global _settings
    if _settings is None or reload:
        # Always reload environment files to pick up any changes
        load_env_if_present(force_reload=True)

        validate_mandatory_env_vars()

        try:
            # Backward compatibility: map deprecated NOETL_SCHEMA_ENSURE -> NOETL_SCHEMA_VALIDATE if new not set
            if 'NOETL_SCHEMA_VALIDATE' not in os.environ and 'NOETL_SCHEMA_ENSURE' in os.environ:
                os.environ['NOETL_SCHEMA_VALIDATE'] = os.environ['NOETL_SCHEMA_ENSURE']
                print("DEPRECATED: NOETL_SCHEMA_ENSURE detected -> set NOETL_SCHEMA_VALIDATE (will be removed soon).")
            if 'NOETL_SCHEMA_VALIDATE' not in os.environ:
                raise RuntimeError("Missing required environment variable NOETL_SCHEMA_VALIDATE (true/false)")

            _settings = Settings(
                raw_env=dict(os.environ),
                # Admin DB
                POSTGRES_USER=os.environ['POSTGRES_USER'],
                POSTGRES_PASSWORD=os.environ['POSTGRES_PASSWORD'],
                POSTGRES_DB=os.environ['POSTGRES_DB'],
                POSTGRES_HOST=os.environ['POSTGRES_HOST'],
                POSTGRES_PORT=os.environ['POSTGRES_PORT'],
                # NoETL principal
                NOETL_USER=os.environ['NOETL_USER'],
                NOETL_PASSWORD=os.environ['NOETL_PASSWORD'],
                NOETL_SCHEMA=os.environ['NOETL_SCHEMA'],
                # Runtime
                NOETL_HOST=os.environ['NOETL_HOST'],
                NOETL_PORT=os.environ['NOETL_PORT'],
                NOETL_ENABLE_UI=os.environ['NOETL_ENABLE_UI'],
                NOETL_DEBUG=os.environ['NOETL_DEBUG'],
                # Server identity
                NOETL_SERVER_URL=os.environ['NOETL_SERVER_URL'],
                NOETL_SERVER_NAME=os.environ['NOETL_SERVER_NAME'],
                # Server runtime config
                NOETL_SERVER=os.environ['NOETL_SERVER'],
                NOETL_SERVER_WORKERS=os.environ['NOETL_SERVER_WORKERS'],
                NOETL_SERVER_RELOAD=os.environ['NOETL_SERVER_RELOAD'],
                # Drop schema & validation
                NOETL_DROP_SCHEMA=os.environ['NOETL_DROP_SCHEMA'],
                NOETL_SCHEMA_VALIDATE=os.environ['NOETL_SCHEMA_VALIDATE'],
                NOETL_AUTO_RECREATE_RUNTIME=os.environ['NOETL_AUTO_RECREATE_RUNTIME'],
                NOETL_HEARTBEAT_RETRY_AFTER=os.environ['NOETL_HEARTBEAT_RETRY_AFTER'],
                NOETL_RUNTIME_SWEEP_INTERVAL=os.environ['NOETL_RUNTIME_SWEEP_INTERVAL'],
                NOETL_RUNTIME_OFFLINE_SECONDS=os.environ['NOETL_RUNTIME_OFFLINE_SECONDS'],
                NOETL_DISABLE_METRICS=os.environ['NOETL_DISABLE_METRICS'],
                NOETL_SERVER_METRICS_INTERVAL=os.environ['NOETL_SERVER_METRICS_INTERVAL'],
                NOETL_SERVER_LABELS=os.environ.get('NOETL_SERVER_LABELS'),
                HOSTNAME=os.environ.get('HOSTNAME'),
                # NATS Configuration
                NATS_URL=os.environ.get('NATS_URL', 'nats://noetl:noetl@localhost:30422'),
                NATS_USER=os.environ.get('NATS_USER', 'noetl'),
                NATS_PASSWORD=os.environ.get('NATS_PASSWORD', 'noetl'),
                NATS_STREAM=os.environ.get('NATS_STREAM', 'NOETL_COMMANDS'),
                NATS_CONSUMER=os.environ.get('NATS_CONSUMER', 'noetl_worker_pool'),
                NATS_SUBJECT=os.environ.get('NATS_SUBJECT', 'noetl.commands'),
            )
        except Exception as e:
            print(f"FATAL: Failed to initialize settings: {e}", file=sys.stderr)
            sys.exit(1)

    return _settings


def get_worker_settings(reload: bool = False) -> WorkerSettings:
    """
    Retrieve worker runtime settings with validation.
    """
    global _worker_settings
    if _worker_settings is None or reload:
        load_env_if_present(force_reload=True)
        env = os.environ
        _worker_settings = WorkerSettings(
            raw_env=dict(env),
            NOETL_WORKER_POOL_RUNTIME=env.get('NOETL_WORKER_POOL_RUNTIME', 'cpu'),
            NOETL_WORKER_POOL_NAME=env.get('NOETL_WORKER_POOL_NAME'),
            NOETL_SERVER_URL=env.get('NOETL_SERVER_URL', 'http://localhost:8082'),
            NOETL_WORKER_BASE_URL=env.get('NOETL_WORKER_BASE_URL', 'http://queue-worker'),
            NOETL_WORKER_CAPACITY=env.get('NOETL_WORKER_CAPACITY'),
            NOETL_WORKER_LABELS=env.get('NOETL_WORKER_LABELS'),
            POD_NAMESPACE=env.get('POD_NAMESPACE'),
            NOETL_WORKER_ID=env.get('NOETL_WORKER_ID'),
            NOETL_DEREGISTER_RETRIES=env.get('NOETL_DEREGISTER_RETRIES', '3'),
            NOETL_DEREGISTER_BACKOFF=env.get('NOETL_DEREGISTER_BACKOFF', '0.5'),
            NOETL_DISABLE_METRICS=env.get('NOETL_DISABLE_METRICS', 'true'),
            NOETL_WORKER_METRICS_INTERVAL=env.get('NOETL_WORKER_METRICS_INTERVAL', '60'),
            NOETL_WORKER_HEARTBEAT_INTERVAL=env.get('NOETL_WORKER_HEARTBEAT_INTERVAL', '15'),
            HOSTNAME=env.get('HOSTNAME'),
            NOETL_HOST=env.get('NOETL_HOST', 'localhost'),
            NOETL_PORT=env.get('NOETL_PORT', '8082'),
            NOETL_SERVER_NAME=env.get('NOETL_SERVER_NAME'),
            NOETL_MAX_WORKERS=env.get('NOETL_MAX_WORKERS', '8'),
        )
    return _worker_settings


# Lazy-loaded settings singleton for direct import
# Usage: from noetl.core.config import settings
class _SettingsProxy:
    """Proxy to lazily load settings on first access."""
    def __getattr__(self, name):
        return getattr(get_settings(), name)

settings = _SettingsProxy()
