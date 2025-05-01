import logging
import os
import asyncio

def get_log_level() -> int:
    log_level: int = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    return log_level

def get_log_level_name() -> str:
    return logging.getLevelName(get_log_level())

def is_on(value: str) -> bool:
    return str(value).lower() in ("true", "1", "yes", "on", "y", "t")

def is_off(value: str) -> bool:
    return str(value).lower() in ("false", "0", "no", "off", "n", "f")

async def mkdir(dir_path):
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: os.makedirs(dir_path, exist_ok=True))
        return {f"Directory created": {dir_path}}
    except Exception as e:
        raise f"Failed to create directory: {dir_path}. Error: {e}"
