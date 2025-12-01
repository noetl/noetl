import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from jinja2 import Environment
from kubernetes.config.config_exception import ConfigException

from noetl.plugin.tools.container import execute_container_task


def _build_context():
    return {"execution_id": "exec-123", "job_id": "job-abc"}


def _job_status(succeeded=1, failed=0, condition=None):
    now = datetime.datetime.now(datetime.timezone.utc)
    status = SimpleNamespace(
        succeeded=succeeded,
        failed=failed,
        conditions=[condition] if condition else None,
        start_time=now,
        completion_time=now,
    )
    spec = SimpleNamespace(backoff_limit=0)
    return SimpleNamespace(status=status, spec=spec)


def _pod(exit_code=0):
    terminated = SimpleNamespace(exit_code=exit_code)
    state = SimpleNamespace(terminated=terminated)
    container_status = SimpleNamespace(state=state)
    status = SimpleNamespace(container_statuses=[container_status])
    metadata = SimpleNamespace(name="pod-1")
    return SimpleNamespace(metadata=metadata, status=status)


@patch("noetl.plugin.tools.container.executor.resolve_script", return_value="#!/bin/bash\necho hi\n")
@patch("noetl.plugin.tools.container.executor.client.BatchV1Api")
@patch("noetl.plugin.tools.container.executor.client.CoreV1Api")
@patch("noetl.plugin.tools.container.executor.time.sleep", lambda *_args, **_kwargs: None)
@patch("noetl.plugin.tools.container.executor.config.load_incluster_config")
@patch("noetl.plugin.tools.container.executor.config.load_kube_config")
def test_execute_container_success(
    mock_kube_config,
    mock_incluster_config,
    mock_core_api_cls,
    mock_batch_api_cls,
    _mock_resolve_script,
):
    mock_incluster_config.side_effect = ConfigException("not in cluster")
    mock_kube_config.return_value = None

    core_api = MagicMock()
    batch_api = MagicMock()
    mock_core_api_cls.return_value = core_api
    mock_batch_api_cls.return_value = batch_api

    batch_api.read_namespaced_job_status.return_value = _job_status()
    core_api.list_namespaced_pod.return_value = SimpleNamespace(items=[_pod()])
    core_api.read_namespaced_pod_log.return_value = "done"

    env = Environment()
    context = _build_context()
    task_config = {
        "name": "init-tradedb",
        "tool": "container",
        "runtime": {
            "provider": "kubernetes",
            "namespace": "noetl",
            "image": "alpine:3",
            "timeoutSeconds": 5,
            "files": [
                {
                    "uri": "./scripts/tradedb/tradedb_ddl.sql",
                    "source": {"type": "file"},
                    "mountPath": "/ddl.sql",
                }
            ],
        },
        "script": {
            "uri": "./scripts/sample.sh",
            "source": {"type": "file"},
        },
    }

    result = execute_container_task(task_config, context, env)

    assert result["status"] == "success"
    assert "job_name" in result["data"]
    assert any(file_entry["path"].endswith("/ddl.sql") for file_entry in result["data"]["files"])
    batch_api.create_namespaced_job.assert_called_once()
    core_api.create_namespaced_config_map.assert_called_once()


@patch("noetl.plugin.tools.container.executor.resolve_script", return_value="#!/bin/bash\nexit 1\n")
@patch("noetl.plugin.tools.container.executor.client.BatchV1Api")
@patch("noetl.plugin.tools.container.executor.client.CoreV1Api")
@patch("noetl.plugin.tools.container.executor.time.sleep", lambda *_args, **_kwargs: None)
@patch("noetl.plugin.tools.container.executor.config.load_incluster_config")
@patch("noetl.plugin.tools.container.executor.config.load_kube_config")
def test_execute_container_failure_returns_error(
    mock_kube_config,
    mock_incluster_config,
    mock_core_api_cls,
    mock_batch_api_cls,
    _mock_resolve_script,
):
    mock_incluster_config.return_value = None

    core_api = MagicMock()
    batch_api = MagicMock()
    mock_core_api_cls.return_value = core_api
    mock_batch_api_cls.return_value = batch_api

    condition = SimpleNamespace(type="Failed", status="True", reason="CrashLoop", message="bad exit")
    batch_api.read_namespaced_job_status.return_value = _job_status(succeeded=0, failed=1, condition=condition)
    core_api.list_namespaced_pod.return_value = SimpleNamespace(items=[_pod(exit_code=1)])
    core_api.read_namespaced_pod_log.return_value = "boom"

    env = Environment()
    context = _build_context()
    task_config = {
        "name": "init-tradedb",
        "tool": "container",
        "runtime": {
            "provider": "kubernetes",
            "namespace": "noetl",
            "image": "alpine:3",
            "timeoutSeconds": 5,
        },
        "script": {
            "uri": "./scripts/sample.sh",
            "source": {"type": "file"},
        },
    }

    result = execute_container_task(task_config, context, env)

    assert result["status"] == "error"
    assert "job_name" in result["data"]
    assert "CrashLoop" in result["error"]


def test_missing_runtime_raises():
    env = Environment()
    context = _build_context()
    task_config = {
        "tool": "container",
        "script": {
            "uri": "./scripts/sample.sh",
            "source": {"type": "file"},
        },
    }
    with pytest.raises(ValueError):
        execute_container_task(task_config, context, env)
