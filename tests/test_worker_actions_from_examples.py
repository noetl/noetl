"""Execute selected example steps to validate core worker action types.

Each test isolates a task from an example playbook and invokes
``execute_task`` directly. This ensures the Python, HTTP, and DuckDB
implementations behave as expected. Run with:

```
pytest tests/test_worker_actions_from_examples.py -q
```
"""

import os
import tempfile
from unittest.mock import patch

import yaml
from jinja2 import Environment, BaseLoader

from noetl.action import execute_task


def _jinja_env():
    env = Environment(loader=BaseLoader())
    env.globals["env"] = {}
    return env


def test_python_action_from_weather_example():
    data = yaml.safe_load(open("examples/weather/weather_example.yaml"))
    step = next(s for s in data["workflow"] if s["step"] == "report_warm")
    task_config = {
        "type": "python",
        "code": step["code"],
        "with": {"city": {"name": "TestCity"}, "temperature": 30},
    }
    context = {}
    env = _jinja_env()
    result = execute_task(task_config, "report_warm", context, env)
    assert result["status"] == "success"
    assert result["data"]["city"] == "TestCity"


def test_http_action_from_github_example():
    data = yaml.safe_load(open("examples/github/github_metrics_example.yaml"))
    step = next(s for s in data["workflow"] if s["step"] == "fetch_github_repo")
    task_config = {
        "type": "http",
        "method": step.get("method", "GET"),
        "endpoint": step["endpoint"],
        "headers": step.get("headers", {}),
    }
    context = {"workload": {"api_base_url": "https://example.com", "repository": "demo/repo"}}
    env = _jinja_env()

    def _mock_request(self, method, url, headers=None, params=None, json=None, data=None, files=None):
        class Dummy:
            def __init__(self, url):
                self.status_code = 200
                self.headers = {'Content-Type': 'application/json'}
                self.url = url
                self.elapsed = type("E", (), {"total_seconds": lambda self: 0})()
                self.text = "{}"
                self.is_success = True
            def json(self):
                return {"name": "demo"}
        return Dummy(url)

    with patch("httpx.Client.request", new=_mock_request):
        result = execute_task(task_config, "fetch_github_repo", context, env)
    assert result["status"] == "success"
    assert result["data"]["data"]["name"] == "demo"


class _DummyConn:
    def __init__(self):
        import duckdb

        self.conn = duckdb.connect()

    def execute(self, sql):
        sql_upper = sql.strip().upper()
        if sql_upper.startswith("INSTALL") or sql_upper.startswith("LOAD"):
            return self
        return self.conn.execute(sql)

    def fetchall(self):
        return self.conn.fetchall()

    def fetchone(self):
        return self.conn.fetchone()

    def close(self):
        self.conn.close()


def test_duckdb_action_from_github_example():
    data = yaml.safe_load(open("examples/github/github_metrics_example.yaml"))
    step = next(s for s in data["workflow"] if s["step"] == "extract_repo_metrics")
    task_config = {"type": "duckdb", "command": step["command"], "with": {"db_type": "sqlite", "db_path": ":memory:"}}
    context = {
        "repo_name": "demo",
        "repo_full_name": "demo/full",
        "stars_count": 1,
        "forks_count": 1,
        "language": "Python",
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-02T00:00:00",
        "execution_id": "testexec",
    }
    env = _jinja_env()
    os.environ["NOETL_DATA_DIR"] = tempfile.mkdtemp()
    with patch("noetl.action.duckdb.connect", return_value=_DummyConn()):
        result = execute_task(task_config, "extract_repo_metrics", context, env)
    assert result["status"] == "success"
