import sys
import yaml
from jinja2 import Template, StrictUndefined
from jinja2.exceptions import UndefinedError
from noetl.util import setup_logger

logger = setup_logger(__name__, include_location=True)

def render_jinja2_template(template_str, context):
    try:
        template = Template(template_str, undefined=StrictUndefined)
        return template.render(context)
    except UndefinedError as e:
        raise RuntimeError(f"Template rendering error: {e}")

def expect_dict(obj, name):
    if not isinstance(obj, dict):
        raise TypeError(f"{name} must be a dictionary")

def expect_list(obj, name):
    if not isinstance(obj, list):
        raise TypeError(f"{name} must be a list")

def validate_key_value_dict(obj, name):
    expect_dict(obj, name)
    for k, v in obj.items():
        if not isinstance(k, str):
            raise TypeError(f"{name} key must be a string, got {type(k)}")

def validate_context(context):
    expect_dict(context, "context")
    if "jobId" not in context:
        raise ValueError("context.jobId is required")
    if "state" not in context:
        raise ValueError("context.state is required")
    if "steps" not in context or not isinstance(context["steps"], list):
        raise ValueError("context.steps must be a list")
    if "results" not in context or not isinstance(context["results"], dict):
        raise ValueError("context.results must be a dictionary")

def validate_action(action):
    required_fields = ["action", "method", "name", "desc", "endpoint", "params"]
    for field in required_fields:
        if field not in action:
            raise ValueError(f"Action is missing required field: {field}")
    if "params" in action:
        validate_key_value_dict(action["params"], "params")
    if "run" in action:
        expect_list(action["run"], "run (nested)")
        for item in action["run"]:
            validate_action(item)

def validate_task(task):
    if "task" not in task:
        raise ValueError("Task is missing 'task' name")
    if "run" not in task:
        raise ValueError(f"Task '{task['task']}' must contain a 'run' block")
    expect_list(task["run"], f"task[{task['task']}].run")
    for item in task["run"]:
        validate_action(item)

def validate_workbook(workbook):
    expect_list(workbook, "workbook")
    for task in workbook:
        validate_task(task)

def validate_workflow_step(step):
    if "step" not in step:
        raise ValueError("Workflow step is missing 'step' name")
    if "run" not in step:
        raise ValueError(f"Workflow step '{step['step']}' must contain a 'run' block")
    expect_list(step["run"], f"workflow[{step['step']}].run")
    for run_item in step["run"]:
        if not isinstance(run_item, dict):
            raise ValueError("Each run item must be a dictionary")
        if not any(k in run_item for k in ("task", "action", "playbook")):
            raise ValueError("Each run item must specify one of: task, action, playbook")
    if "next" in step:
        expect_list(step["next"], f"workflow[{step['step']}].next")
        for next_clause in step["next"]:
            if "when" not in next_clause or "then" not in next_clause:
                raise ValueError("Each 'next' clause must have 'when' and 'then' fields")
            if not isinstance(next_clause["then"], list):
                raise TypeError("next.then must be a list of step names")

def validate_workflow(workflow):
    expect_list(workflow, "workflow")
    for step in workflow:
        validate_workflow_step(step)

def validate_playbook_structure(playbook):
    required_fields = ["apiVersion", "kind", "name", "path", "environment", "context", "workbook", "workflow"]
    for field in required_fields:
        if field not in playbook:
            raise ValueError(f"Missing required top-level field: {field}")
    if playbook["kind"] != "Playbook":
        raise ValueError("kind must be 'Playbook'")

    validate_key_value_dict(playbook["environment"], "environment")
    validate_context(playbook["context"])
    validate_workbook(playbook["workbook"])
    validate_workflow(playbook["workflow"])

    logger.success("Playbook validation passed")

def main(filepath, context=None):
    if context is None:
        context = {}
    with open(filepath, "r", encoding="utf-8") as f:
        raw = f.read()

    logger.info("Parsing Playbook YAML with unrendered Jinja2 expressions.")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ValueError(f"YAML parsing failed: {e}")

    logger.info("Validating playbook.")
    validate_playbook_structure(data)

    logger.success("Playbook is valid.")

if __name__ == "__main__":
    test_payload = {
        "job": {"uuid": "1234-abcd"},
        "context": {"token": "test-token", "state": "pending"},
        "environment": {
            "api_url": "https://api.example.com/orders",
            "validation_url": "https://api.example.com/validate",
            "audit_url": "https://api.example.com/audit"
        },
        "results": {
            "fetch_orders": ["order1", "order2"]
        },
        "result": {
            "customer": {"list": ["alice", "bob"]}
        }
    }

    if len(sys.argv) != 2:
        logger.warning("Usage: python validate_playbook.py <playbook.noetl.yaml>")
        sys.exit(1)

    playbook_file = sys.argv[1]
    main(playbook_file, test_payload)
