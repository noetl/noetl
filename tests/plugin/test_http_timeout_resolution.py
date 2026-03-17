from noetl.tools.http.executor import _resolve_http_timeout_seconds


def test_resolve_http_timeout_clamps_to_worker_budget(monkeypatch):
    monkeypatch.setenv("NOETL_HTTP_REQUEST_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("NOETL_WORKER_COMMAND_TIMEOUT_SECONDS", "30")

    assert _resolve_http_timeout_seconds(None) == 30.0
    assert _resolve_http_timeout_seconds(90) == 30.0
    assert _resolve_http_timeout_seconds("25") == 25.0


def test_resolve_http_timeout_rejects_unbounded_or_invalid_values(monkeypatch):
    monkeypatch.setenv("NOETL_HTTP_REQUEST_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("NOETL_WORKER_COMMAND_TIMEOUT_SECONDS", "180")

    assert _resolve_http_timeout_seconds("") == 45.0
    assert _resolve_http_timeout_seconds("invalid") == 45.0
    assert _resolve_http_timeout_seconds(0) == 0.1
    assert _resolve_http_timeout_seconds(-10) == 0.1
