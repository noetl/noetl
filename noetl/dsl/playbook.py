import base64
import yaml
from jinja2 import Environment, StrictUndefined, TemplateSyntaxError
from fastapi import HTTPException
from typing import Any, Dict


def render_template(raw_template: str, context: Dict[str, Any]) -> str:
    try:
        env = Environment(undefined=StrictUndefined)
        template = env.from_string(raw_template)
        return template.render(context)
    except TemplateSyntaxError as e:
        raise ValueError(f"Jinja2 Template Error: {e.message}")


def parse_yaml(yaml_str: str) -> Dict[str, Any]:
    try:
        return yaml.safe_load(yaml_str)
    except yaml.YAMLError as e:
        raise ValueError(f"YAML Parsing Error: {e}")


def validate_playbook_structure(playbook: Dict[str, Any]):
    required_fields = ["apiVersion", "kind", "name", "path", "environment", "context", "workbook", "workflow"]
    for field in required_fields:
        if field not in playbook:
            raise ValueError(f"Missing required field in playbook: {field}")


def register_playbook_base64(content_base64: str, render_context: Dict[str, Any]) -> Dict[str, Any]:
    try:
        decoded_template = base64.b64decode(content_base64).decode("utf-8")
        rendered_yaml = render_template(decoded_template, render_context)
        parsed_playbook = parse_yaml(rendered_yaml)
        validate_playbook_structure(parsed_playbook)

        return {
            "status": "success",
            "message": f"Playbook '{parsed_playbook['name']}' successfully validated.",
            "parsed": parsed_playbook
        }

    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")
