import pytest
from jinja2 import Environment

from noetl.tools import execute_task
from noetl.tools.mcp import execute_mcp_task


class _FakeResponse:
    def __init__(self, text, headers=None, status_code=200):
        self.text = text
        self.headers = headers or {}
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status={self.status_code}")


class _FakeAsyncClient:
    timeouts = []

    def __init__(self, *args, **kwargs):
        self.__class__.timeouts.append(kwargs.get("timeout"))
        self.posts = []
        self.gets = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url):
        self.gets.append(url)
        return _FakeResponse("ok")

    async def post(self, endpoint, json, headers):
        self.posts.append((endpoint, json, headers))
        if json["method"] == "initialize":
            return _FakeResponse(
                'data: {"jsonrpc":"2.0","id":1,"result":{"serverInfo":{"name":"fake"}}}',
                headers={"mcp-session-id": "session-1"},
            )
        assert headers["Mcp-Session-Id"] == "session-1"
        return _FakeResponse(
            'data: {"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"pod-a Running"}]}}'
        )


class _FakeErrorAsyncClient(_FakeAsyncClient):
    async def post(self, endpoint, json, headers):
        self.posts.append((endpoint, json, headers))
        if json["method"] == "initialize":
            return _FakeResponse(
                'data: {"jsonrpc":"2.0","id":1,"result":{"serverInfo":{"name":"fake"}}}',
                headers={"mcp-session-id": "session-1"},
            )
        return _FakeResponse('data: {"jsonrpc":"2.0","id":2,"error":{"message":"tool failed"}}')


def test_tools_package_preserves_execute_task_export():
    assert callable(execute_task)


@pytest.mark.asyncio
async def test_execute_mcp_tool_call(monkeypatch):
    _FakeAsyncClient.timeouts = []
    monkeypatch.setattr("noetl.tools.mcp.executor.httpx.AsyncClient", _FakeAsyncClient)

    result = await execute_mcp_task(
        {
            "server": "kubernetes",
            "endpoint": "http://mcp.example/mcp",
            "method": "tools/call",
            "tool": "pods_list_in_namespace",
            "arguments": {"namespace": "{{ namespace }}"},
        },
        {"namespace": "noetl"},
        Environment(),
        {},
    )

    assert result["status"] == "ok"
    assert result["server"] == "kubernetes"
    assert result["method"] == "tools/call"
    assert result["tool"] == "pods_list_in_namespace"
    assert result["arguments"] == {"namespace": "noetl"}
    assert result["text"] == "pod-a Running"
    assert _FakeAsyncClient.timeouts == [60.0]


@pytest.mark.asyncio
async def test_execute_mcp_health(monkeypatch):
    _FakeAsyncClient.timeouts = []
    monkeypatch.setattr("noetl.tools.mcp.executor.httpx.AsyncClient", _FakeAsyncClient)

    result = await execute_mcp_task(
        {
            "endpoint": "http://mcp.example/mcp",
            "method": "health",
        },
        {},
        Environment(),
        {},
    )

    assert result["status"] == "ok"
    assert result["healthy"] is True
    assert _FakeAsyncClient.timeouts == [60.0]


@pytest.mark.asyncio
async def test_execute_mcp_timeout_is_bounded(monkeypatch):
    _FakeAsyncClient.timeouts = []
    monkeypatch.setenv("NOETL_MCP_REQUEST_TIMEOUT_SECONDS", "999")
    monkeypatch.setenv("NOETL_WORKER_COMMAND_TIMEOUT_SECONDS", "2")
    monkeypatch.setattr("noetl.tools.mcp.executor.httpx.AsyncClient", _FakeAsyncClient)

    result = await execute_mcp_task(
        {
            "endpoint": "http://mcp.example/mcp",
            "method": "health",
            "timeout_seconds": "inf",
        },
        {},
        Environment(),
        {},
    )

    assert result["status"] == "ok"
    assert _FakeAsyncClient.timeouts == [2.0]


@pytest.mark.asyncio
async def test_execute_mcp_timeout_zero_keeps_safe_floor(monkeypatch):
    _FakeAsyncClient.timeouts = []
    monkeypatch.setattr("noetl.tools.mcp.executor.httpx.AsyncClient", _FakeAsyncClient)

    result = await execute_mcp_task(
        {
            "endpoint": "http://mcp.example/mcp",
            "method": "health",
            "timeout_seconds": 0,
        },
        {},
        Environment(),
        {},
    )

    assert result["status"] == "ok"
    assert _FakeAsyncClient.timeouts == [0.1]


@pytest.mark.asyncio
async def test_execute_mcp_returns_structured_error(monkeypatch):
    _FakeErrorAsyncClient.timeouts = []
    monkeypatch.setattr("noetl.tools.mcp.executor.httpx.AsyncClient", _FakeErrorAsyncClient)

    result = await execute_mcp_task(
        {
            "endpoint": "http://mcp.example/mcp",
            "method": "tools/call",
            "tool": "pods_list",
        },
        {},
        Environment(),
        {},
    )

    assert result["status"] == "error"
    assert result["error"] == "tool failed"
