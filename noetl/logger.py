import os
import asyncio
import re
import sys
import json
import logging
from typing import Dict, Any, Optional, List, Union, TYPE_CHECKING
import psycopg
from psycopg.rows import dict_row
from contextlib import contextmanager
import traceback

if TYPE_CHECKING:
    from noetl.schema import DatabaseSchema



try:
    from psycopg_pool import ConnectionPool
except ImportError:
    ConnectionPool = None

_db_schema = None

def get_db_schema() -> 'DatabaseSchema':
    """
    Get a global instance of DatabaseSchema.
    Returns:
        A DatabaseSchema instance
    """
    global _db_schema
    if _db_schema is None:
        from noetl.schema import DatabaseSchema
        _db_schema = DatabaseSchema(auto_setup=True)
    return _db_schema

def log_error(
    error: Exception,
    error_type: str,
    template_string: str,
    context_data: Dict,
    input_data: Dict = None,
    execution_id: str = None,
    step_id: str = None,
    step_name: str = None
) -> None:
    """
    Log a template rendering error to the database.
    Args:
        error: The exception that occurred
        error_type: The type of error (e.g., "template_rendering", "sql_template_rendering")
        template_string: The template that failed to render
        context_data: The context data used for rendering
        input_data: Additional input data related to the error
        execution_id: The ID of the execution where the error occurred
        step_id: The ID of the step where the error occurred
        step_name: The name of the step where the error occurred
    """
    try:
        logger.error(f"Error: {error_type} - {error}")
        logger.error(f"Details: {template_string[:100]}...")
        
        try:
            db_schema = get_db_schema()
            stack_trace = ''.join(traceback.format_exc())
            db_schema.log_error(
                error_type=error_type,
                error_message=str(error),
                execution_id=execution_id,
                step_id=step_id,
                step_name=step_name,
                template_string=template_string,
                context_data=context_data,
                stack_trace=stack_trace,
                input_data=input_data,
                output_data=None,
                severity="error"
            )
        except ImportError as import_error:
            logger.warning(f"Could not log to database due to import error: {import_error}")
            logger.warning("This is expected during initialization or in test environments")
        except Exception as db_error:
            logger.error(f"Failed to log template error to database: {db_error}")
    except Exception as log_error:
        logger.error(f"Failed to log error: {log_error}")




SUCCESS_LEVEL = 25
LOG_SEVERITY = {
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "SUCCESS": "SUCCESS",
    "WARNING": "WARNING",
    "ERROR": "ERROR",
    "CRITICAL": "CRITICAL"
}

LOG_COLORS = {
    "DEBUG": "\033[36m",      # Cyan
    "INFO": "\033[37m",       # White
    "SUCCESS": "\033[32m",    # Green
    "WARNING": "\033[33m",    # Yellow
    "ERROR": "\033[31m",      # Red
    "CRITICAL": "\033[35m"    # Magenta
}
RESET_COLOR = "\033[0m"

logging.addLevelName(SUCCESS_LEVEL, "SUCCESS")

class CustomLogger(logging.Logger):
    def success(self, message, *args, **kwargs):
        if self.isEnabledFor(SUCCESS_LEVEL):
            self.log(SUCCESS_LEVEL, message, *args, **kwargs, stacklevel=2)

def stringify_extra(value):
    if isinstance(value, (list, dict)):
        return str(value)
    else:
        return value


class CustomFormatter(logging.Formatter):

    def __init__(self, fmt="%(message)s", include_location=False, highlight_scope=True):
        super().__init__(fmt)
        self.include_location = include_location
        self.highlight_scope = highlight_scope

    def format(self, record):
        level_name = LOG_SEVERITY.get(record.levelname, record.levelname)
        level_color = LOG_COLORS.get(record.levelname, "")

        if hasattr(record, "scope"):
            scope_highlight = f"\033[32m{record.scope}\033[0m"
        else:
            scope_highlight = ""
        location = ""
        if self.include_location and hasattr(record, "module") and hasattr(record, "funcName") and hasattr(record,
                                                                                                           "lineno"):
            location = f"\033[1;33m({record.module}:{record.funcName}:{record.lineno})\033[0m"

        metadata_line = f"{level_color}[{level_name}]{RESET_COLOR} {scope_highlight} {location}".strip()

        if isinstance(record.msg, (dict, list)):
            message = str(record.msg)
        else:
            message = str(record.msg)

        message_split = message.splitlines()
        if len(message_split) > 1:
            message_line = f"     Message: {message_split[0]}"
            for line in message_split[1:]:
                message_line += f"\n             {line}"
        else:
            message_line = f"     Message: {message}" #.strip()

        extra_items = [
            f"{key}: {stringify_extra(value)}"
            for key, value in record.__dict__.items()
            if key not in [
                "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "process", "processName", "scope", "name", "taskName"
            ]
        ]
        extra_info = ""
        if extra_items:
            extra_info = f"\n     {' '.join(extra_items)}"
        formatted_log = f"{metadata_line}\n{message_line}{extra_info}"
        return formatted_log


class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_dict = {
            "level": record.levelname,
            "message": record.msg,
            "time": self.formatTime(record, self.datefmt),
        }
        if hasattr(record, "scope"):
            log_dict["scope"] = record.scope
        if hasattr(record, "module") and hasattr(record, "funcName") and hasattr(record, "lineno"):
            log_dict["location"] = {
                "module": record.module,
                "function": record.funcName,
                "line": record.lineno,
            }
        return json.dumps(log_dict, ensure_ascii=False)

def setup_logger(name: str, include_location=False, use_json=False):
    logging.setLoggerClass(CustomLogger)
    logger = logging.getLogger(name)

    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(logging.DEBUG)
        if use_json:
            stream_handler.setFormatter(JSONFormatter())
        else:
            stream_handler.setFormatter(CustomFormatter(include_location=include_location))
        logger.addHandler(stream_handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger



logger = setup_logger(__name__, include_location=True)