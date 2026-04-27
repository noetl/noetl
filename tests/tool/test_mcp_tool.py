import pytest
from jinja2 import Environment

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
    def __init__(self, *args, **kwargs):
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


@pytest.mark.asyncio
async def test_execute_mcp_tool_call(monkeypatch):
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


@pytest.mark.asyncio
async def test_execute_mcp_health(monkeypatch):
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


@pytest.mark.asyncio
async def test_execute_mcp_returns_structured_error(monkeypatch):
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
