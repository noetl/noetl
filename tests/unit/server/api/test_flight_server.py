"""Unit tests for R-2.3 Phase A Arrow Flight do_get server."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

import pytest

# pyarrow.flight is part of the standard pyarrow distribution; if it's
# unavailable on the test host we skip the whole module.
pyarrow_flight = pytest.importorskip("pyarrow.flight")
pa = pytest.importorskip("pyarrow")

from noetl.server.api.result.flight_server import (
    ARROW_STREAM_MEDIA_TYPE,
    NoetlFlightServer,
    _extract_rows,
)


# ---------------------------------------------------------------------------
# _extract_rows
# ---------------------------------------------------------------------------


def test_extract_rows_wrapped_shape():
    """Top-level {columns, rows} → returns the rows list."""
    data = {
        "columns": ["a", "b"],
        "rows": [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}],
    }
    rows = _extract_rows(data)
    assert rows == [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]


def test_extract_rows_nested_under_data():
    """{"data": {columns, rows}} → returns the nested rows."""
    data = {
        "status": "Success",
        "data": {"columns": ["x"], "rows": [{"x": 42}]},
        "duration_ms": 12,
    }
    rows = _extract_rows(data)
    assert rows == [{"x": 42}]


def test_extract_rows_no_rows_field():
    """Object missing `rows` at every level → None."""
    assert _extract_rows({"stdout": "hello", "exit_code": 0}) is None
    assert _extract_rows({"data": {"columns": ["x"]}}) is None


def test_extract_rows_array_rows_returns_none():
    """Array-row shape (rows[0] not a dict) is unsupported in Phase A."""
    data = {"columns": ["a", "b"], "rows": [[1, "x"], [2, "y"]]}
    assert _extract_rows(data) is None


def test_extract_rows_non_object_input():
    """Non-object inputs return None."""
    assert _extract_rows([1, 2, 3]) is None  # type: ignore[arg-type]
    assert _extract_rows("hello") is None  # type: ignore[arg-type]
    assert _extract_rows(None) is None  # type: ignore[arg-type]


def test_extract_rows_empty_list_returns_empty_list():
    """Empty rows list is still tabular shape; returns []."""
    # Callers can decide whether to encode an empty batch or fall through;
    # the function itself preserves the shape.
    assert _extract_rows({"rows": []}) == []


# ---------------------------------------------------------------------------
# NoetlFlightServer round-trip
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    """Pick a free TCP port — Flight server's port is set at start_in_thread."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_until_listening(port: int, timeout_seconds: float = 5.0) -> None:
    """Poll until the Flight server's port accepts a connection."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.2)
        try:
            s.connect(("127.0.0.1", port))
            s.close()
            return
        except OSError:
            time.sleep(0.05)
        finally:
            s.close()
    raise TimeoutError(f"Flight server on port {port} never started")


@pytest.fixture
def flight_server_with_stub_store(monkeypatch):
    """Spin up a NoetlFlightServer on a free port with a stubbed
    `default_store.resolve` returning a deterministic rowset.
    Yields ``(server, port, expected_rows)`` and tears the server
    down on exit.
    """
    port = _find_free_port()
    expected_rows = [
        {"id": 1, "username": "user_001", "password": "[REDACTED]"},
        {"id": 2, "username": "user_002", "password": "[REDACTED]"},
        {"id": 3, "username": "user_003", "password": "[REDACTED]"},
    ]

    async def fake_resolve(ref: Any) -> Any:
        # The Flight server passes the ticket bytes decoded as the URI.
        assert isinstance(ref, str)
        assert ref.startswith("noetl://"), ref
        return {"data": {"columns": ["id", "username", "password"], "rows": expected_rows}}

    monkeypatch.setattr(
        "noetl.server.api.result.flight_server.default_store",
        type("StubStore", (), {"resolve": staticmethod(fake_resolve)}),
    )

    server = NoetlFlightServer(location=f"grpc://127.0.0.1:{port}")
    server.start_in_thread()
    _wait_until_listening(port)
    try:
        yield server, port, expected_rows
    finally:
        server.shutdown()


def test_flight_do_get_round_trip_returns_rows(flight_server_with_stub_store):
    """End-to-end: client submits a noetl:// ticket → server resolves
    via the (stubbed) store + streams Arrow IPC back → client reads
    rows that match what the store returned."""
    _server, port, expected_rows = flight_server_with_stub_store

    client = pyarrow_flight.connect(f"grpc://127.0.0.1:{port}")
    ticket = pyarrow_flight.Ticket(b"noetl://execution/12345/result/big_select/abcd1234")
    reader = client.do_get(ticket)
    table = reader.read_all()

    assert table.num_rows == 3
    decoded = table.to_pylist()
    assert decoded == expected_rows


def test_flight_do_get_non_tabular_raises_unavailable(monkeypatch):
    """Non-tabular result → server raises FlightUnavailableError so the
    client can fall back to HTTP `/api/result/resolve`."""
    port = _find_free_port()

    async def fake_resolve(ref: Any) -> Any:
        # Shell-tool result shape: no `rows` field at any level.
        return {"stdout": "hello world", "exit_code": 0, "duration_ms": 12}

    monkeypatch.setattr(
        "noetl.server.api.result.flight_server.default_store",
        type("StubStore", (), {"resolve": staticmethod(fake_resolve)}),
    )

    server = NoetlFlightServer(location=f"grpc://127.0.0.1:{port}")
    server.start_in_thread()
    _wait_until_listening(port)
    try:
        client = pyarrow_flight.connect(f"grpc://127.0.0.1:{port}")
        ticket = pyarrow_flight.Ticket(b"noetl://execution/12345/result/shell_step/x")
        with pytest.raises(pyarrow_flight.FlightUnavailableError):
            client.do_get(ticket).read_all()
    finally:
        server.shutdown()


def test_flight_get_flight_info_returns_unimplemented(monkeypatch):
    """Phase A doesn't expose FlightInfo — consumers must submit
    Tickets directly.  The server raises FlightServerError with a
    descriptive message (this pyarrow version doesn't expose a
    dedicated `Unimplemented` variant)."""
    port = _find_free_port()

    async def fake_resolve(ref: Any) -> Any:  # pragma: no cover - not reached
        return {}

    monkeypatch.setattr(
        "noetl.server.api.result.flight_server.default_store",
        type("StubStore", (), {"resolve": staticmethod(fake_resolve)}),
    )

    server = NoetlFlightServer(location=f"grpc://127.0.0.1:{port}")
    server.start_in_thread()
    _wait_until_listening(port)
    try:
        client = pyarrow_flight.connect(f"grpc://127.0.0.1:{port}")
        descriptor = pyarrow_flight.FlightDescriptor.for_path("any", "path")
        with pytest.raises((pyarrow_flight.FlightServerError, pyarrow_flight.FlightInternalError)) as exc_info:
            client.get_flight_info(descriptor)
        # The descriptive message round-trips through gRPC so consumers
        # can log it.
        assert "Phase A" in str(exc_info.value)
    finally:
        server.shutdown()


def test_arrow_stream_media_type_matches_python_constant():
    """The constant re-exported from this module matches the Python
    storage layer's own constant so cross-stack consumers can switch
    on a single string."""
    from noetl.core.storage.arrow_ipc import (
        ARROW_STREAM_MEDIA_TYPE as STORAGE_MEDIA_TYPE,
    )
    assert ARROW_STREAM_MEDIA_TYPE == STORAGE_MEDIA_TYPE
    assert ARROW_STREAM_MEDIA_TYPE == "application/vnd.apache.arrow.stream"
