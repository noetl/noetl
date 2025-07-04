import os
import asyncio
import re
import sys
import json
import logging
import base64
import yaml
from collections import OrderedDict
from datetime import datetime, timedelta, timezone, date
import random
import string
from typing import Dict, Any, Optional, List, Union
from jinja2 import Environment, StrictUndefined, BaseLoader

# logger = setup_logger(__name__, include_location=True)
#===================================
#  custom logger
#===================================

SUCCESS_LEVEL = 25
LOG_SEVERITY = {
    "DEBUG": "🔍",
    "INFO": "ℹ️",
    "SUCCESS": "✅",
    "WARNING": "⚠️",
    "ERROR": "❌",
    "CRITICAL": "🔥"
}

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
        icon = LOG_SEVERITY.get(record.levelname, "ℹ️")
        if hasattr(record, "scope"):
            scope_highlight = f"\033[32m{record.scope}\033[0m"
        else:
            scope_highlight = ""
        location = ""
        if self.include_location and hasattr(record, "module") and hasattr(record, "funcName") and hasattr(record,
                                                                                                           "lineno"):
            location = f"\033[1;33m({record.module}:{record.funcName}:{record.lineno})\033[0m"

        metadata_line = f"{icon} [{record.levelname}] {scope_highlight} {location}".strip()

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

#===================================
#  jinja2 template rendering
#===================================

def render_template(env: Environment, template: Any, context: Dict, rules: Dict = None) -> Any:
    """
    Render a template using the Jinja2 environment.

    Args:
        env: The Jinja2 environment
        template: The template to render
        context: The context to use for rendering
        rules: Additional rules for rendering

    Returns:
        The rendered template
    """
    if isinstance(template, str) and '{{' in template and '}}' in template:
        logger.debug(f"Render template: {template}")
        logger.debug(f"Render template context keys: {list(context.keys())}")
        if 'city' in context:
            logger.debug(f"Render template city value: {context['city']}, Type: {type(context['city'])}")
        if rules:
            logger.debug(f"Render template rules: {rules}")

    render_ctx = dict(context)
    if rules:
        render_ctx.update(rules)

    if isinstance(template, str) and '{{' in template and '}}' in template:
        try:
            expr = template.strip()
            if expr == '{{}}':
                return ""
            if expr.startswith('{{') and expr.endswith('}}'):
                var_path = expr[2:-2].strip()
                if not any(op in var_path for op in ['==', '!=', '<', '>', '+', '-', '*', '/', '|', ' if ', ' else ']):
                    if '.' not in var_path and var_path.strip() in render_ctx:
                        return render_ctx.get(var_path.strip())
                    elif '.' in var_path:
                        parts = var_path.split('.')
                        value = render_ctx
                        valid_path = True
                        for part in parts:
                            part = part.strip()
                            if isinstance(value, dict) and part in value:
                                value = value.get(part)
                            else:
                                valid_path = False
                                break
                        if valid_path:
                            return value

            template_obj = env.from_string(template)
            try:
                rendered = template_obj.render(**render_ctx)
            except Exception as e:
                logger.error(f"Template rendering error: {e}, template: {template}")
                return None

            if (rendered.startswith('[') and rendered.endswith(']')) or \
                    (rendered.startswith('{') and rendered.endswith('}')):
                try:
                    return json.loads(rendered)
                except json.JSONDecodeError:
                    pass

            if rendered.strip() == "":
                return ""

            return rendered
        except Exception as e:
            logger.error(f"Template rendering error: {e}, template: {template}")
            return ""
    elif isinstance(template, dict):
        if not template:
            return template
        return {k: render_template(env, v, render_ctx, rules) for k, v in template.items()}
    elif isinstance(template, list):
        return [render_template(env, item, render_ctx, rules) for item in template]
    return template

def quote_jinja2_expressions(yaml_text):
    """
    Jinja2 expressions to double quotes.
    """
    jinja_expr_pattern = re.compile(r'''
        ^(\s*[^:\n]+:\s*)         # YAML key and colon with optional indent
        (?!["'])                  # Not already quoted
        (.*{{.*}}.*?)             # Contains Jinja2 template
        (?<!["'])\s*$             # Not ending with a quote
    ''', re.VERBOSE)

    def replacer(match):
        key_part = match.group(1)
        value_part = match.group(2).strip()
        return f'{key_part}"{value_part}"'

    fixed_lines = []
    for line in yaml_text.splitlines():
        fixed_line = jinja_expr_pattern.sub(replacer, line)
        fixed_lines.append(fixed_line)
    return "\n".join(fixed_lines)


#===================================
#  time calendar (დრო)
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
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Exception):
        return str(value)
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
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, date):
            return obj.isoformat()
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
# connections
#===================================

def get_pgdb_connection(
    db_name: str = None,
    user: str = None,
    password: str = None,
    host: str = None,
    port: str = None,
    schema: str = None
) -> str:
    db_name = db_name or os.environ.get('POSTGRES_DB', 'noetl')
    user = user or os.environ.get('NOETL_USER', 'noetl')
    password = password or os.environ.get('NOETL_PASSWORD', 'noetl')
    host = host or os.environ.get('POSTGRES_HOST', 'localhost')
    port = port or os.environ.get('POSTGRES_PORT', '5434')
    schema = schema or os.environ.get('NOETL_SCHEMA', 'noetl')

    return f"dbname={db_name} user={user} password={password} host={host} port={port} options='-c search_path={schema}'"
