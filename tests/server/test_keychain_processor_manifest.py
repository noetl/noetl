import pytest

from noetl.server.keychain_processor import process_keychain_section


class _FakeResponse:
    status_code = 200

    def json(self):
        return {"status": "success"}


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        self.posts = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, json=None):
        self.posts.append((url, json))
        return _FakeResponse()


@pytest.mark.asyncio
async def test_process_keychain_section_returns_manifest_not_resolved_values(monkeypatch):
    import noetl.server.keychain_processor as processor

    monkeypatch.setattr(processor.httpx, "AsyncClient", _FakeAsyncClient)

    result = await process_keychain_section(
        keychain_section=[
            {
                "name": "openai_token",
                "kind": "static",
                "scope": "global",
                "map": {"api_key": "placeholder-secret"},
            }
        ],
        catalog_id=42,
        execution_id=123,
        workload_vars={},
        api_base_url="http://noetl.test",
    )

    assert result == {
        "entries": {
            "openai_token": {
                "kind": "static",
                "fields": ["api_key"],
            }
        }
    }
    assert "placeholder-secret" not in str(result)
