import os
import sys
from typing import Optional, Dict, Any, ClassVar
from pydantic import BaseModel, Field, ConfigDict, model_validator, field_validator
from pathlib import Path
from noetl.common import get_bool


_ENV_LOADED = False

def _load_env_file(path: str) -> None:
    """
    Minimal .env loader: loads KEY=VALUE pairs into os.environ if not already set.
    - Ignores empty lines and lines starting with '#'
    - Supports values wrapped in single or double quotes
    - Does not override existing environment variables
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
                if key not in os.environ:
                    os.environ[key] = value
    except Exception:
        pass

def load_env_if_present() -> None:
    """
    Load environment variables from a specified .env file once (best-effort).
    Only loads when NOETL_ENV_FILE is provided; otherwise relies on the current process environment.
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    custom = os.environ.get("NOETL_ENV_FILE")
    if custom:
        _load_env_file(custom)
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
        # Server runtime
        'NOETL_SERVER', 'NOETL_SERVER_WORKERS', 'NOETL_SERVER_RELOAD',
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

    # Server runtime (required; no defaults)
    server_runtime: str = Field(..., alias="NOETL_SERVER")            # "uvicorn" | "gunicorn" | "auto"
    server_workers: int = Field(..., alias="NOETL_SERVER_WORKERS")    # >= 1
    server_reload: bool = Field(..., alias="NOETL_SERVER_RELOAD")     # true/false

    @field_validator('postgres_user', 'postgres_password', 'postgres_db', 'postgres_host',
                     'postgres_port', 'noetl_user', 'noetl_password', 'noetl_schema', 'host', 'server_runtime', mode='before')
    def validate_not_empty_str(cls, v):
        if not isinstance(v, str) or not v.strip():
            raise ValueError("Value cannot be empty or whitespace only")
        return v.strip()

    @field_validator('enable_ui', 'debug', 'noetl_drop_schema', 'server_reload', mode='before')
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
        return (Path(__file__).resolve().parent / "ui" / "build")

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

_settings: Optional[Settings] = None

def get_settings() -> Settings:
    """
    Get application settings. Validates environment variables on first call.
    """
    global _settings
    if _settings is None:
        load_env_if_present()

        validate_mandatory_env_vars()

        try:
            # Backward compatibility: map deprecated NOETL_SCHEMA_ENSURE -> NOETL_SCHEMA_VALIDATE if new not set
            if 'NOETL_SCHEMA_VALIDATE' not in os.environ and 'NOETL_SCHEMA_ENSURE' in os.environ:
                os.environ['NOETL_SCHEMA_VALIDATE'] = os.environ['NOETL_SCHEMA_ENSURE']
                print("DEPRECATED: NOETL_SCHEMA_ENSURE detected -> set NOETL_SCHEMA_VALIDATE (will be removed soon).")
            if 'NOETL_SCHEMA_VALIDATE' not in os.environ:
                raise RuntimeError("Missing required environment variable NOETL_SCHEMA_VALIDATE (true/false)")

            _settings = Settings(
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
                # Runtime (cast to proper types)
                NOETL_HOST=os.environ['NOETL_HOST'],
                NOETL_PORT=int(os.environ['NOETL_PORT']),
                NOETL_ENABLE_UI=get_bool(os.environ['NOETL_ENABLE_UI']),
                NOETL_DEBUG=get_bool(os.environ['NOETL_DEBUG']),
                # Server runtime config
                NOETL_SERVER=os.environ['NOETL_SERVER'],
                NOETL_SERVER_WORKERS=int(os.environ['NOETL_SERVER_WORKERS']),
                NOETL_SERVER_RELOAD=get_bool(os.environ['NOETL_SERVER_RELOAD']),
                # Drop schema flag
                NOETL_DROP_SCHEMA=get_bool(os.environ['NOETL_DROP_SCHEMA']),
                NOETL_SCHEMA_VALIDATE=get_bool(os.environ['NOETL_SCHEMA_VALIDATE'])
            )
        except Exception as e:
            print(f"FATAL: Failed to initialize settings: {e}", file=sys.stderr)
            sys.exit(1)

    return _settings
