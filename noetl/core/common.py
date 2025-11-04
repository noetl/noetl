import os
import sys
import asyncio
import json
import logging
import yaml
import time
import threading
from collections import OrderedDict
from datetime import datetime, timedelta, timezone, date
import random
import string
from decimal import Decimal
from typing import Dict, Any, List, Union, Type, TypeVar
import psycopg
from contextlib import contextmanager
from pydantic import BaseModel, ConfigDict, ValidationError
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


# =============================================================================
# Pydantic Common Models and Utilities
# =============================================================================

class AppBaseModel(BaseModel):
    """
    Base Pydantic model with common configuration.
    
    Used across all NoETL API schemas to provide consistent:
    - ORM mode support (from_attributes=True)
    - Automatic string coercion for numeric types
    """
    model_config = ConfigDict(from_attributes=True, coerce_numbers_to_str=True)


T = TypeVar("T", bound=BaseModel)


def transform(class_constructor: Type[T], arg: dict) -> T:
    """
    Generic function to transform a dict into a Pydantic model instance with error logging.

    Args:
        class_constructor: Any Pydantic model class.
        arg: Dictionary of data to pass to the model.

    Returns:
        An instance of the model.

    Raises:
        ValidationError: If the data does not conform to the model.
    """
    try:
        return class_constructor(**arg)
    except ValidationError as e:
        logger.error(
            f"{class_constructor.__name__} Validation error: "
            f"{json.dumps(e.errors(include_input=False, include_url=False))}"
        )
        raise


# =============================================================================
# Snowflake ID Generation
# =============================================================================


try:
    from psycopg_pool import ConnectionPool, AsyncConnectionPool
except ImportError:
    ConnectionPool = None
    AsyncConnectionPool = None


# Snowflake ID generator (41-bit ms timestamp, 10-bit node id, 12-bit sequence)
_SNOWFLAKE_EPOCH_MS = int(os.environ.get("NOETL_SNOWFLAKE_EPOCH_MS", str(int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000))))
_SNOWFLAKE_NODE_ID = int(os.environ.get("NOETL_NODE_ID", os.environ.get("NOETL_SHARD_ID", "0"))) & 0x3FF  # 10 bits
_SNOWFLAKE_LOCK = threading.Lock()
_SNOWFLAKE_LAST_TS = 0
_SNOWFLAKE_SEQ = 0


def get_snowflake_id() -> int:
    global _SNOWFLAKE_LAST_TS, _SNOWFLAKE_SEQ
    with _SNOWFLAKE_LOCK:
        ts = int(time.time() * 1000)
        if ts < _SNOWFLAKE_LAST_TS:
            ts = _SNOWFLAKE_LAST_TS
        if ts == _SNOWFLAKE_LAST_TS:
            _SNOWFLAKE_SEQ = (_SNOWFLAKE_SEQ + 1) & 0xFFF
            if _SNOWFLAKE_SEQ == 0:
                while True:
                    ts = int(time.time() * 1000)
                    if ts > _SNOWFLAKE_LAST_TS:
                        break
        else:
            _SNOWFLAKE_SEQ = 0
        _SNOWFLAKE_LAST_TS = ts
        elapsed = ts - _SNOWFLAKE_EPOCH_MS
        if elapsed < 0:
            elapsed = 0
        return ((elapsed & ((1 << 41) - 1)) << (10 + 12)) | ((_SNOWFLAKE_NODE_ID & 0x3FF) << 12) | (_SNOWFLAKE_SEQ & 0xFFF)


def get_snowflake_id_str() -> str:
    return str(get_snowflake_id())


def snowflake_id_to_str(snowflake_id: Union[int, str, None]) -> str:
    """
    Convert snowflake ID to string for API/UI compatibility.
    External systems may fail to support 64-bit integers.
    """
    if snowflake_id is None:
        return ""
    return str(snowflake_id)


def snowflake_id_to_int(snowflake_id: Union[int, str, None]) -> int:
    """
    Convert snowflake ID string back to int for database operations.
    Returns 0 for invalid/None values.
    """
    if snowflake_id is None:
        return 0
    if isinstance(snowflake_id, int):
        return snowflake_id
    if isinstance(snowflake_id, str):
        try:
            return int(snowflake_id)
        except (ValueError, TypeError):
            return 0
    return 0


def normalize_execution_id_for_db(execution_id: Union[int, str, None]) -> int:
    """
    Normalize execution_id for consistent database operations.
    
    This is a centralized utility to ensure all execution_id values are converted
    from Snowflake ID strings to integers before being used in SQL parameters.
    This prevents catalog_id lookup failures and queue insert issues.
    
    Args:
        execution_id: String, integer, or None Snowflake ID
        
    Returns:
        Integer representation of the execution_id, or 0 for invalid/None values
        
    Raises:
        ValueError: If execution_id is provided but cannot be converted to a valid integer
    """
    if execution_id is None:
        return 0
        
    if isinstance(execution_id, int):
        return execution_id
        
    if isinstance(execution_id, str):
        try:
            converted = int(execution_id)
            if converted == 0 and execution_id not in ('0', ''):
                # Only raise error if non-zero string couldn't be converted properly
                # This allows '0' and '' to pass through as 0
                return converted
            return converted
        except (ValueError, TypeError):
            raise ValueError(f"Invalid execution_id: {execution_id}")
    
    raise ValueError(f"Unsupported execution_id type: {type(execution_id)}")


def convert_snowflake_ids_for_api(data: Any) -> Any:
    """
    Recursively convert snowflake ID fields to strings for API responses.
    Handles execution_id, event_id, parent_event_id, parent_execution_id fields.
    """
    if isinstance(data, dict):
        result = {}
        snowflake_fields = ['execution_id', 'event_id', 'parent_event_id', 'parent_execution_id', 'id']
        for key, value in data.items():
            if key in snowflake_fields:
                result[key] = snowflake_id_to_str(value)
            else:
                result[key] = convert_snowflake_ids_for_api(value)
        return result
    elif isinstance(data, list):
        return [convert_snowflake_ids_for_api(item) for item in data]
    else:
        return data

#===================================
#  time calendar
#===================================

def generate_id() -> str:
    start_date_time = datetime.now()
    timestamp = start_date_time.strftime("%Y%m%d_%H%M%S")
    microseconds = f"{start_date_time.microsecond:06d}"
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{timestamp}_{microseconds}_{suffix}"

def duration_seconds(start_date, end_date) -> int | None:
    return int((start_date - end_date).total_seconds())

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def today_utc() -> datetime:
    now = now_utc()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)

def week_start_utc(reference: datetime = None) -> datetime:
    if reference is None:
        reference = now_utc()
    monday = reference - timedelta(days=reference.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)

def add_days(base: datetime, days: int) -> datetime:
    return base + timedelta(days=days)

def add_weeks(base: datetime, weeks: int) -> datetime:
    return base + timedelta(weeks=weeks)

def month_end(date: datetime) -> datetime:
    next_month = date.replace(day=28) + timedelta(days=4)
    last_day = next_month - timedelta(days=next_month.day)
    return last_day.replace(hour=23, minute=59, second=59, microsecond=999999)

def format_iso8601(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()

def format_utc(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%d %H:%M:%S UTC')

def parse_iso8601(iso_str: str) -> datetime:
    return datetime.fromisoformat(iso_str)

def days_between(start: datetime, end: datetime) -> int:
    delta = end - start
    return delta.days

def is_weekend(date: datetime) -> bool:
    return date.weekday() >= 5

def next_weekday(date: datetime, weekday: int) -> datetime:
    days_ahead = weekday - date.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return date + timedelta(days=days_ahead)

#===================================
# environment
#===================================


def log_level() -> int:
    log_level: int = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    return log_level

def log_level_name() -> str:
    return logging.getLevelName(log_level())

def is_on(value: str) -> bool:
    return str(value).lower() in ("true", "1", "yes", "on", "y", "t")

def is_off(value: str) -> bool:
    return str(value).lower() in ("false", "0", "no", "off", "n", "f")

def get_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on", "pass", "ignore")
    if isinstance(value, (int, float)):
        return value != 0
    return False

async def mkdir(dir_path):
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: os.makedirs(dir_path, exist_ok=True))
        return {f"Directory created": {dir_path}}
    except Exception as e:
        raise f"Failed to create directory: {dir_path}. Error: {e}"

#===================================
# serialization
#===================================


def make_serializable(value):
    # Handle Jinja2 Undefined objects
    try:
        from jinja2 import Undefined
        if isinstance(value, Undefined):
            return None
    except ImportError:
        pass
    
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Exception):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: make_serializable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [make_serializable(v) for v in value]
    if hasattr(value, "__dict__"):
        return {k: make_serializable(v) for k, v in value.__dict__.items()}
    return value


class SafeEncoder(json.JSONEncoder):
    def default(self, obj):
        return None

class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        # Handle Jinja2 Undefined objects
        try:
            from jinja2 import Undefined
            if isinstance(obj, Undefined):
                return None
        except ImportError:
            pass
            
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, date):
            return obj.isoformat()
        elif isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

def ordered_yaml_dump(data):
    def convert_ordered_dict(obj):
        if isinstance(obj, OrderedDict):
            return {k: convert_ordered_dict(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_ordered_dict(i) for i in obj]
        return obj

    cleaned_data = convert_ordered_dict(data)
    return yaml.dump(cleaned_data, default_flow_style=False, sort_keys=False)

def ordered_yaml_load(stream):
    class OrderedLoader(yaml.SafeLoader):
        pass

    def construct_mapping(loader, node):
        loader.flatten_mapping(node)
        return OrderedDict(loader.construct_pairs(node))

    OrderedLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_mapping
    )
    return yaml.load(stream, OrderedLoader)

def encode_version(version: str) -> str:
    major, minor, patch = map(int, version.split("."))
    return f"{major:03d}.{minor:03d}.{patch:03d}"

def decode_version(encoded_version: str) -> str:
    major, minor, patch = encoded_version.split(".")
    return f"{int(major)}.{int(minor)}.{int(patch)}"

def increment_version(version: str) -> str:
    major, minor, patch = map(int, version.split("."))

    patch += 1
    if patch > 999:
        patch = 0
        minor += 1
        if minor > 999:
            minor = 0
            major += 1
            if major > 999:
                raise ValueError("Version overflow -> version limit is '999.999.999'")

    return f"{major}.{minor}.{patch}"

#===================================
# merging dictionaries and lists
#===================================

def deep_merge(dest: Union[Dict, List, Any], source: Union[Dict, List, Any]) -> Union[Dict, List, Any]:
    if isinstance(dest, dict) and isinstance(source, dict):
        result = dest.copy()
        for key, value in source.items():
            if key in result and isinstance(result[key], (dict, list)) and isinstance(value, (dict, list)):
                result[key] = deep_merge(result[key], value)
            else:
                result[key] = value
        return result
    elif isinstance(dest, list) and isinstance(source, list):
        if all(isinstance(item, dict) for item in dest + source):
            common_keys = set()
            for item in dest + source:
                common_keys.update(item.keys())
            if 'name' in common_keys:
                result = dest.copy()
                source_names = {item.get('name'): item for item in source if 'name' in item}
                for i, item in enumerate(result):
                    if 'name' in item and item['name'] in source_names:
                        result[i] = deep_merge(item, source_names[item['name']])
                        del source_names[item['name']]

                result.extend(source_names.values())
                return result

        result = dest.copy()
        result.extend(source)
        return result
    else:
        return source

#===================================
# connection strings
#===================================

def get_pgdb_connection(
    db_name: str = None,
    user: str = None,
    password: str = None,
    host: str = None,
    port: str = None,
    schema: str = None,
    use_admin: bool = False
) -> str:
    """
    Get PostgreSQL database connection string.
    
    Args:
        use_admin: If True, use POSTGRES_* credentials for admin operations.
                   If False, use NOETL_* credentials for application operations.
    """
    if use_admin:
        db_name = db_name or os.environ.get('POSTGRES_DB')
        user = user or os.environ.get('POSTGRES_USER')
        password = password or os.environ.get('POSTGRES_PASSWORD')
    else:
        db_name = db_name or os.environ.get('POSTGRES_DB')
        user = user or os.environ.get('NOETL_USER')
        password = password or os.environ.get('NOETL_PASSWORD')
    
    host = host or os.environ.get('POSTGRES_HOST')
    port = port or os.environ.get('POSTGRES_PORT')
    schema = schema or os.environ.get('NOETL_SCHEMA')
    
    # Debug logging
    logger.debug(f"Database connection parameters: db={db_name}, user={user}, host={host}, port={port}, schema={schema}, use_admin={use_admin}")
    
    if not user or not password:
        logger.warning(f"Missing database credentials! user={user}, password={'*' * len(password) if password else None}")
        logger.warning(f"Available env vars: NOETL_USER={os.environ.get('NOETL_USER')}, NOETL_PASSWORD={'*' * len(os.environ.get('NOETL_PASSWORD', '')) if os.environ.get('NOETL_PASSWORD') else None}")
        logger.warning(f"POSTGRES_USER={os.environ.get('POSTGRES_USER')}, POSTGRES_PASSWORD={'*' * len(os.environ.get('POSTGRES_PASSWORD', '')) if os.environ.get('POSTGRES_PASSWORD') else None}")
    
    return f"dbname={db_name} user={user} password={password} host={host} port={port} hostaddr='' gssencmode=disable options='-c search_path={schema}'"

#===================================
# postgres pool (sync and async)
#===================================

db_pool = None

async_db_pool = None


def initialize_db_pool():
    global db_pool
    if db_pool is None and ConnectionPool:
        try:
            connection_string = get_pgdb_connection()
            db_pool = ConnectionPool(conninfo=connection_string, min_size=2, max_size=20, name="sync_legacy_noetl_server_connection", open=False)
            db_pool.open()
            logger.info("Database connection pool initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize connection pool: {e}. Trying to use direct connections.")
            db_pool = None
    return db_pool

from contextlib import asynccontextmanager

async def initialize_async_db_pool():
    global async_db_pool
    if async_db_pool is None and AsyncConnectionPool:
        try:
            connection_string = get_pgdb_connection()
            async_db_pool = AsyncConnectionPool(conninfo=connection_string, min_size=2, max_size=20, name="legacy_noetl_server_connection", open=False)
            await async_db_pool.open()
            logger.info("Async database connection pool initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize async connection pool: {e}. Falling back to direct async connection.")
            async_db_pool = None
    return async_db_pool

@contextmanager
def get_db_connection(optional=False):
    """
    Get a database connection from the sync pool or create a new one.
    
    Args:
        optional (bool): If True, return None instead of raising an exception when the connection fails.
                         This allows the application to continue without a database connection.
    """
    pool = initialize_db_pool()
    if pool:
        conn = None
        try:
            conn = pool.getconn()
            yield conn
        except Exception as pool_error:
            logger.warning(f"Connection pool error: {pool_error}. Falling back to direct connection.")
        else:
            # Successfully used pool connection
            return
        finally:
            # Always return connection to pool if we got one
            if conn:
                try:
                    pool.putconn(conn)
                except Exception as e:
                    logger.warning(f"Error returning connection to pool: {e}")

    # Direct connection fallback (only reached if pool failed)
    conn = None
    try:
        conn = psycopg.connect(get_pgdb_connection())
        yield conn
    except Exception as e:
        logger.error(f"Connection failed: {e}")
        if optional:
            logger.warning("Database connection is optional, continuing without it.")
            yield None
        else:
            raise
    finally:
        if conn:
            conn.close()

from contextlib import asynccontextmanager

@asynccontextmanager
async def get_async_db_connection(optional: bool = False):
    """
    Get an async database connection from the async pool.
    No fallbacks - fails fast if pool connection cannot be established.

    Args:
        optional (bool): If True, yields None instead of raising an exception when connection fails.
    """
    pool = await initialize_async_db_pool()
    if not pool:
        error_msg = "Database connection pool not initialized"
        logger.error(error_msg)
        if optional:
            yield None
            return
        else:
            raise RuntimeError(error_msg)
    
    # Use pool connection - no fallbacks
    async with pool.connection() as conn:
        yield conn
