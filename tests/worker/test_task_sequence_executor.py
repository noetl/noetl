import importlib.util
from types import SimpleNamespace
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[2] / "noetl/worker/task_sequence_executor.py"
_SPEC = importlib.util.spec_from_file_location("task_sequence_executor", _MODULE_PATH)
_TASK_SEQ_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC is not None and _SPEC.loader is not None
_SPEC.loader.exec_module(_TASK_SEQ_MODULE)
TaskSequenceExecutor = _TASK_SEQ_MODULE.TaskSequenceExecutor


def _to_namespace(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{k: _to_namespace(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_to_namespace(v) for v in value]
    return value


def _render_template(template: str, context: dict):
    if not isinstance(template, str) or "{{" not in template:
        return template
    expr = template.strip()
    if expr.startswith("{{") and expr.endswith("}}"):
        expr = expr[2:-2].strip()
    eval_context = {k: _to_namespace(v) for k, v in context.items()}
    return "True" if bool(eval(expr, {"__builtins__": {}}, eval_context)) else "False"


def _render_dict(data: dict, _context: dict) -> dict:
    return data


@pytest.mark.asyncio
async def test_http_error_status_code_drives_retry_rule():
    calls = {"count": 0}

    async def fake_tool_executor(_kind: str, _config: dict, _ctx: dict):
        calls["count"] += 1
        if calls["count"] == 1:
            # Mirrors HTTP plugin error shape: status=error with status code in data payload.
            return {
                "status": "error",
                "error": "HTTP 500: Internal Server Error",
                "data": {"status_code": 500},
            }
        return {"status_code": 200, "data": {"ok": True}}

    executor = TaskSequenceExecutor(
        tool_executor=fake_tool_executor,
        render_template=_render_template,
        render_dict=_render_dict,
    )

    tasks = [
        {
            "name": "fetch_detail",
            "kind": "http",
            "url": "https://example.test/detail",
            "spec": {
                "policy": {
                    "rules": [
                        {
                            "when": "{{ outcome.status == 'error' and outcome.http.status in [500] }}",
                            "then": {"do": "retry", "attempts": 2, "backoff": "none", "delay": 0},
                        },
                        {
                            "when": "{{ outcome.status == 'error' }}",
                            "then": {"do": "fail"},
                        },
                        {"else": {"then": {"do": "continue"}}},
                    ]
                }
            },
        }
    ]

    result = await executor.execute(tasks=tasks, base_context={})

    assert result["status"] == "ok"
    assert calls["count"] == 2
    assert result["results"]["fetch_detail"]["status_code"] == 200


@pytest.mark.asyncio
async def test_http_error_infers_retryable_for_429():
    calls = {"count": 0}

    async def fake_tool_executor(_kind: str, _config: dict, _ctx: dict):
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "status": "error",
                "error": "HTTP 429: Too Many Requests",
                "data": {"status_code": 429},
            }
        return {"status_code": 200}

    executor = TaskSequenceExecutor(
        tool_executor=fake_tool_executor,
        render_template=_render_template,
        render_dict=_render_dict,
    )

    tasks = [
        {
            "name": "fetch_detail",
            "kind": "http",
            "url": "https://example.test/detail",
            "spec": {
                "policy": {
                    "rules": [
                        {
                            "when": "{{ outcome.status == 'error' and outcome.error.retryable }}",
                            "then": {"do": "retry", "attempts": 2, "backoff": "none", "delay": 0},
                        },
                        {
                            "when": "{{ outcome.status == 'error' }}",
                            "then": {"do": "fail"},
                        },
                        {"else": {"then": {"do": "continue"}}},
                    ]
                }
            },
        }
    ]

    result = await executor.execute(tasks=tasks, base_context={})

    assert result["status"] == "ok"
    assert calls["count"] == 2
