# ==================================================================================================================== #
#                                             INTERPOLATION MODULE                                                     #
# ==================================================================================================================== #
#                    Interpolate functions for loading configurations and applying variables.                          #
# ==================================================================================================================== #
from jinja2 import Template, Environment, FileSystemLoader, DebugUndefined
import re
import os
import yaml
import json
import copy
import datetime
import random
import string

from noetl.shared import setup_logger

logger = setup_logger(__name__, include_location=True)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             TEMPLATE FILTERS                                                         #
# -------------------------------------------------------------------------------------------------------------------- #

def dict2list(d) -> list or None:
    dict_items_type = type({}.items())
    if isinstance(d, list):
        return d
    elif isinstance(d, dict):
        return d.get("items", [])
    elif isinstance(d, dict_items_type):
        d = dict(d)
        return d.get("items", [])
    elif callable(d):
        d = d()
        return dict2list(d)
    elif hasattr(d, "values"):
        return list(d.values())
    raise TypeError(f"Unsupported dict2list type: {type(d)}")


# -------------------------------------------------------------------------------------------------------------------- #
#                                             CONFIGURATION LOADING                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

def load_config(file_path) -> dict or None:
    with open(file_path, "r") as f:
        return yaml.safe_load(f)


def load_payload(payload) -> dict or None:
    try:
        if '\n' in payload or ':' in payload:
            logger.info("Loading payload from inline content", extra={"scope": "[Interp]"})
            parsed_payload = yaml.safe_load(payload)
            if not isinstance(parsed_payload, dict):
                raise ValueError("Inline YAML content failed parse to a dictionary.")
            return parsed_payload
        else:
            logger.info("[Interp] Loading payload from file", extra={"scope": "[Interp]"})
            return load_config(payload)
    except yaml.YAMLError as e:
        logger.error(f"YAML parsing error: {e}", extra={"scope": "[Interp]"})
        raise ValueError(f"YAML parsing error: {e}") from e
    except Exception as e:
        logger.error(f"Failed to load payload: {e}", extra={"scope": "[Interp]"})
        raise


# -------------------------------------------------------------------------------------------------------------------- #
#                                             TEMPLATE RENDERING                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def render_template(template, context) -> str or None:
    env = Environment(undefined=DebugUndefined)
    if not isinstance(template, str):
        try:
            template = json.dumps(template)
        except (TypeError, ValueError) as e:
            logger.error(f"Error converting to JSON: {template}. Error: {e}", extra={"scope": "[Interp]"})
            return template
    try:
        rendered = env.from_string(template).render(context)
        return rendered
    except Exception as e:
        logger.error(f"Error rendering template: {template} with context: {context}. Error: {e}", extra={"scope": "[Interp]"})
        return template


def render_payload_template(template_path, config) -> dict or None:
    logger.info(f"[Interp] Loading and rendering template from: {template_path}", extra={"scope": "[Interp]"})

    folder = os.path.dirname(template_path)
    filename = os.path.basename(template_path)
    env = Environment(
        loader=FileSystemLoader(folder),
        undefined=DebugUndefined,
        keep_trailing_newline=True
    )
    env.filters["dict2list"] = dict2list
    template = env.get_template(filename)
    logger.info("[Interp] Rendering template with the provided configuration", extra={"scope": "[Interp]"})
    rendered_data = template.render(config)
    logger.success(f"[Interp] Template successfully rendered from: {template_path}")
    try:
        parsed_data = json.loads(rendered_data)
        return parsed_data
    except json.JSONDecodeError:
        try:
            parsed_data = yaml.safe_load(rendered_data)
            return parsed_data
        except Exception as e:
            logger.error(f"[Interp] Failed to parse rendered template as JSON or YAML: {e}", extra={"scope": "[Interp]"})
            raise


def process_payload(payload) -> dict or None:
    if not isinstance(payload, dict):
        payload = yaml.safe_load(payload)

    context = {
        "system": payload.get("system", {}),
        "variables": payload.get("variables", {}),
    }
    logger.info("Resolving placeholders in the payload.", extra={"scope": "[Interp]"})
    rendered_payload = render_template(payload, context)
    resolved_payload = yaml.safe_load(rendered_payload)
    logger.success(f"Payload placeholders resolved: {resolved_payload}.", extra={"scope": "[Interp]"})
    config_path = resolved_payload.get("config", None)

    if config_path and isinstance(config_path, str):
        if os.path.exists(config_path):
            logger.info(f"Loading workflow from file: {config_path}.", extra={"scope": "[Interp]"})
            with open(config_path, "r") as file:
                config = yaml.safe_load(file)
        else:
            logger.error(f"Workflow file not found: {config_path}", extra={"scope": "[Interp]"})
            raise FileNotFoundError(f"Workflow file not found: {config_path}")
    else:
        logger.info("Using inline workflow", extra={"scope": "[Interp]"})
        config = resolved_payload

    if not isinstance(config, dict):
        logger.error("Workflow configuration must be a dictionary.", extra={"scope": "[Interp]"})
        raise ValueError("[Interp] Invalid workflow configuration format.")

    overridden_config = apply_overrides(config, payload)
    context = {
            "variables": copy.deepcopy(overridden_config.get("variables"),{}),
            "system": copy.deepcopy(overridden_config.get("system", {})),
            **overridden_config.get("system", {}),
            **overridden_config.get("variables", {})

    }
    config_replaced = json.loads(render_template(overridden_config, context))
    template = config_replaced.get("system", {}).get("templatePath")

    if template:
        logger.info("Processing configuration with template", extra={"scope": "[Interp]"})
        render_payload = render_payload_template(template, config_replaced)
        return render_payload

    logger.info("No template provided, returning workflow with overrides applied", extra={"scope": "[Interp]"})
    return config_replaced


# -------------------------------------------------------------------------------------------------------------------- #
#                                             CONFIGURATION OVERRIDES                                                  #
# -------------------------------------------------------------------------------------------------------------------- #


def apply_overrides(config, overrides) -> dict or None:
    def merge_dicts(base, override):
        for key, value in override.items():
            if isinstance(value, dict) and key in base and isinstance(base[key], dict):
                base[key] = merge_dicts(base[key], value)
            else:
                base[key] = value
        return base

    return merge_dicts(config, overrides)


def override_pairs(pairs) -> dict or None:
    result = {}
    for pair in pairs:
        if "=" in pair:
            key, value = pair.split("=", 1)
            result[key] = value
    return result


def parse_overrides(args) -> dict or None:
    overrides = {
        "variables": override_pairs(args.variables),
        "tasks": {}
    }
    for task_params in args.task:
        if task_params:
            task_name = task_params[0]
            overrides["tasks"][task_name] = override_pairs(task_params[1:])
    return overrides


def replace_placeholders(config, variables) -> dict or str or list or None:
    def replace(match):
        key = match.group(1)
        if key in variables:
            return variables[key]
        else:
            logger.warning(f"Missing placeholder context for '{key}'", extra={"scope": "[Interp]"})
            return match.group(0)
    if isinstance(config, dict):
        return {key: replace_placeholders(value, variables) for key, value in config.items()}
    elif isinstance(config, list):
        return [replace_placeholders(item, variables) for item in config]
    elif isinstance(config, str):
        return re.sub(r"\{\{(\w+)\}\}", replace, config)
    else:
        return config



# -------------------------------------------------------------------------------------------------------------------- #
#                                             SYSTEM STAFF                                                             #
# -------------------------------------------------------------------------------------------------------------------- #

def generate_job_id() -> tuple[datetime.datetime, str]:
    start_date_time = datetime.datetime.now()
    timestamp = start_date_time.strftime("%Y%m%d_%H%M%S")
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return start_date_time, f"{timestamp}_{suffix}"


def resolve_path(path_template, context, fallback_dir):
    from jinja2 import Template
    rendered_path = Template(path_template).render(context)
    resolved_path = os.path.abspath(rendered_path)
    parent_dir = os.path.dirname(resolved_path)
    try:
        if not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
            logger.info(f"Created directory for path: {parent_dir}", extra={"scope": "[Interp]"})
    except Exception as e:
        logger.warning(f"Failed to create directory '{parent_dir}'. Falling back to {fallback_dir}. Exception: {e}",
                       extra={"scope": "[Interp]"})
        resolved_path = os.path.join(fallback_dir, os.path.basename(resolved_path))
        fallback_parent_dir = os.path.dirname(resolved_path)
        os.makedirs(fallback_parent_dir, exist_ok=True)
        return resolved_path

    return resolved_path


def resolve_system_paths(config, context, cwd_path) -> tuple[str, str, str]:
    execution_path = resolve_path(
        config.get("system", {}).get("executionPath", "job_{{ jobId }}.json"),
        context,
        cwd_path
    )
    log_path = resolve_path(
        config.get("system", {}).get("logPath", "noetl_{{ jobId }}.log"),
        context,
        cwd_path
    )
    output_path = resolve_path(
        config.get("system", {}).get("outputPath", "output"),
        context,
        cwd_path
    )

    logger.info(f"[Interp] Resolved paths:\n"
                f"[Interp] Execution Path: {execution_path}\n"
                f"[Interp] Log Path: {log_path}\n"
                f"[Interp] Output Path: {output_path}", extra={"scope": "[Interp]"})

    return execution_path, log_path, output_path
