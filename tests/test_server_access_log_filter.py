import logging

from noetl.server.__main__ import AccessLogFilter


def _record(message: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_access_log_filter_suppresses_health_and_pool_status():
    f = AccessLogFilter(("/api/health", "/api/pool/status"))

    assert f.filter(_record('127.0.0.1 - "GET /api/health HTTP/1.1" 200')) is False
    assert f.filter(_record('127.0.0.1 - "GET /api/pool/status HTTP/1.1" 200')) is False
    assert f.filter(_record('127.0.0.1 - "POST /api/events/batch HTTP/1.1" 202')) is True
