import logging
import os

def get_log_level() -> int:
    log_level: int = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    return log_level

def get_log_level_name() -> str:
    return logging.getLevelName(get_log_level())

def is_on(value: str) -> bool:
    return str(value).lower() in ("true", "1", "yes", "on", "y", "t")