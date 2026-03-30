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
                            "when": "{{ output.status == 'error' and output.http.status in [500] }}",
                            "then": {"do": "retry", "attempts": 2, "backoff": "none", "delay": 0},
                        },
                        {
                            "when": "{{ output.status == 'error' }}",
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
                            "when": "{{ output.status == 'error' and output.error.retryable }}",
                            "then": {"do": "retry", "attempts": 2, "backoff": "none", "delay": 0},
                        },
                        {
                            "when": "{{ output.status == 'error' }}",
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


@pytest.mark.asyncio
async def test_task_sequence_jump_overwrites_latest_result_for_same_task_name():
    calls = {"fetch": 0, "route": 0}

    async def fake_tool_executor(_kind: str, config: dict, _ctx: dict):
        task_id = config.get("id")
        if task_id == "fetch":
            calls["fetch"] += 1
            return {"value": calls["fetch"]}
        if task_id == "route":
            calls["route"] += 1
            return {"jump": calls["route"] == 1}
        raise AssertionError(f"Unexpected task id: {task_id}")

    executor = TaskSequenceExecutor(
        tool_executor=fake_tool_executor,
        render_template=_render_template,
        render_dict=_render_dict,
    )

    tasks = [
        {
            "name": "fetch",
            "kind": "python",
            "id": "fetch",
            "spec": {"policy": {"rules": [{"else": {"then": {"do": "continue"}}}]}},
        },
        {
            "name": "route",
            "kind": "python",
            "id": "route",
            "spec": {
                "policy": {
                    "rules": [
                        {
                            "when": "{{ output.status == 'ok' and output.data.jump }}",
                            "then": {"do": "jump", "to": "fetch"},
                        },
                        {"else": {"then": {"do": "continue"}}},
                    ]
                }
            },
        },
    ]

    result = await executor.execute(tasks=tasks, base_context={})

    assert result["status"] == "ok"
    assert calls["fetch"] == 2
    assert calls["route"] == 2
    assert result["results"]["fetch"] == {"value": 2}
    assert result["results"]["route"] == {"jump": False}


@pytest.mark.asyncio
async def test_task_sequence_unnamed_tasks_use_index_keys():
    async def fake_tool_executor(_kind: str, config: dict, _ctx: dict):
        return {"id": config.get("id")}

    executor = TaskSequenceExecutor(
        tool_executor=fake_tool_executor,
        render_template=_render_template,
        render_dict=_render_dict,
    )

    tasks = [
        {
            "kind": "python",
            "id": "first",
            "spec": {"policy": {"rules": [{"else": {"then": {"do": "continue"}}}]}},
        },
        {
            "kind": "python",
            "id": "second",
            "spec": {"policy": {"rules": [{"else": {"then": {"do": "continue"}}}]}},
        },
    ]

    result = await executor.execute(tasks=tasks, base_context={})

    assert result["status"] == "ok"
    assert result["results"]["task_0"] == {"id": "first"}
    assert result["results"]["task_1"] == {"id": "second"}


@pytest.mark.asyncio
async def test_task_sequence_jump_previous_alias_targets_prior_task():
    calls = {"producer": 0, "route": 0}

    async def fake_tool_executor(_kind: str, config: dict, _ctx: dict):
        task_id = config.get("id")
        if task_id == "producer":
            calls["producer"] += 1
            return {"version": calls["producer"]}
        if task_id == "route":
            calls["route"] += 1
            return {"repeat": calls["route"] == 1}
        raise AssertionError(f"Unexpected task id: {task_id}")

    executor = TaskSequenceExecutor(
        tool_executor=fake_tool_executor,
        render_template=_render_template,
        render_dict=_render_dict,
    )

    tasks = [
        {
            "name": "producer",
            "kind": "python",
            "id": "producer",
            "spec": {"policy": {"rules": [{"else": {"then": {"do": "continue"}}}]}},
        },
        {
            "name": "route",
            "kind": "python",
            "id": "route",
            "spec": {
                "policy": {
                    "rules": [
                        {
                            "when": "{{ output.status == 'ok' and output.data.repeat }}",
                            "then": {"do": "jump", "to": "previous"},
                        },
                        {"else": {"then": {"do": "continue"}}},
                    ]
                }
            },
        },
    ]

    result = await executor.execute(tasks=tasks, base_context={})

    assert result["status"] == "ok"
    assert calls["producer"] == 2
    assert calls["route"] == 2
    assert result["results"]["producer"] == {"version": 2}
    assert result["results"]["route"] == {"repeat": False}


@pytest.mark.asyncio
async def test_task_sequence_missing_reference_error_supports_jump_replay():
    calls = {"producer": 0, "consumer": 0}

    async def fake_tool_executor(_kind: str, config: dict, _ctx: dict):
        task_id = config.get("id")
        if task_id == "producer":
            calls["producer"] += 1
            return {"produced": calls["producer"]}
        if task_id == "consumer":
            calls["consumer"] += 1
            if calls["consumer"] == 1:
                raise FileNotFoundError("result_ref not found for noetl://execution/1/step/producer")
            return {"consumed": True}
        raise AssertionError(f"Unexpected task id: {task_id}")

    executor = TaskSequenceExecutor(
        tool_executor=fake_tool_executor,
        render_template=_render_template,
        render_dict=_render_dict,
    )

    tasks = [
        {
            "name": "producer",
            "kind": "python",
            "id": "producer",
            "spec": {"policy": {"rules": [{"else": {"then": {"do": "continue"}}}]}},
        },
        {
            "name": "consumer",
            "kind": "python",
            "id": "consumer",
            "spec": {
                "policy": {
                    "rules": [
                        {
                            "when": "{{ output.status == 'error' and output.error.code == 'REFERENCE_NOT_AVAILABLE' }}",
                            "then": {"do": "jump", "to": "previous"},
                        },
                        {
                            "when": "{{ output.status == 'error' }}",
                            "then": {"do": "fail"},
                        },
                        {"else": {"then": {"do": "continue"}}},
                    ]
                }
            },
        },
    ]

    result = await executor.execute(tasks=tasks, base_context={})

    assert result["status"] == "ok"
    assert calls["producer"] == 2
    assert calls["consumer"] == 2
    assert result["results"]["producer"] == {"produced": 2}
    assert result["results"]["consumer"] == {"consumed": True}


@pytest.mark.asyncio
async def test_task_sequence_missing_reference_error_reports_reference_code():
    async def fake_tool_executor(_kind: str, _config: dict, _ctx: dict):
        raise FileNotFoundError("artifact reference missing: result_ref key not found")

    executor = TaskSequenceExecutor(
        tool_executor=fake_tool_executor,
        render_template=_render_template,
        render_dict=_render_dict,
    )

    tasks = [
        {
            "name": "consumer",
            "kind": "python",
            "id": "consumer",
            "spec": {
                "policy": {
                    "rules": [
                        {
                            "when": "{{ output.status == 'error' }}",
                            "then": {"do": "fail"},
                        }
                    ]
                }
            },
        }
    ]

    result = await executor.execute(tasks=tasks, base_context={})

    assert result["status"] == "failed"
    assert result["error"]["code"] == "REFERENCE_NOT_AVAILABLE"
    assert result["error"]["retryable"] is True


def test_task_sequence_missing_reference_detection_avoids_refresh_false_positive():
    assert TaskSequenceExecutor._is_missing_reference_error(
        "refresh token missing for upstream auth provider"
    ) is False


@pytest.mark.asyncio
async def test_task_sequence_break_with_only_init_page_fails_when_patient_count_positive():
    async def fake_tool_executor(_kind: str, _config: dict, _ctx: dict):
        return {"status": "noop"}

    executor = TaskSequenceExecutor(
        tool_executor=fake_tool_executor,
        render_template=_render_template,
        render_dict=_render_dict,
    )

    tasks = [
        {
            "name": "init_page",
            "kind": "noop",
            "spec": {"policy": {"rules": [{"else": {"then": {"do": "break"}}}]}},
        },
        {
            "name": "fetch_page",
            "kind": "http",
            "spec": {"policy": {"rules": [{"else": {"then": {"do": "continue"}}}]}},
        },
        {
            "name": "save_page",
            "kind": "postgres",
            "spec": {"policy": {"rules": [{"else": {"then": {"do": "continue"}}}]}},
        },
        {
            "name": "paginate",
            "kind": "noop",
            "spec": {"policy": {"rules": [{"else": {"then": {"do": "continue"}}}]}},
        },
    ]

    result = await executor.execute(
        tasks=tasks,
        base_context={"ctx": {"patient_count": 4}},
    )

    assert result["status"] == "failed"
    assert result["failed_task"] == "init_page"
    assert result["error"]["code"] == "TASK_SEQUENCE_NO_PROGRESS"
    assert result["error"]["retryable"] is False


@pytest.mark.asyncio
async def test_task_sequence_break_with_only_init_page_allows_zero_or_missing_patient_count():
    async def fake_tool_executor(_kind: str, _config: dict, _ctx: dict):
        return {"status": "noop"}

    executor = TaskSequenceExecutor(
        tool_executor=fake_tool_executor,
        render_template=_render_template,
        render_dict=_render_dict,
    )

    tasks = [
        {
            "name": "init_page",
            "kind": "noop",
            "spec": {"policy": {"rules": [{"else": {"then": {"do": "break"}}}]}},
        },
        {
            "name": "fetch_page",
            "kind": "http",
            "spec": {"policy": {"rules": [{"else": {"then": {"do": "continue"}}}]}},
        },
        {
            "name": "save_page",
            "kind": "postgres",
            "spec": {"policy": {"rules": [{"else": {"then": {"do": "continue"}}}]}},
        },
        {
            "name": "paginate",
            "kind": "noop",
            "spec": {"policy": {"rules": [{"else": {"then": {"do": "continue"}}}]}},
        },
    ]

    zero_count_result = await executor.execute(
        tasks=tasks,
        base_context={"ctx": {"patient_count": 0}},
    )
    missing_count_result = await executor.execute(
        tasks=tasks,
        base_context={},
    )

    assert zero_count_result["status"] == "break"
    assert missing_count_result["status"] == "break"
