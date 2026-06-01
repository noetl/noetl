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


def test_flight_get_flight_info_returns_schema_and_endpoint(monkeypatch):
    """R-2.3 Phase C1: `get_flight_info(descriptor)` returns a
    FlightInfo carrying the Arrow schema + row count + a single
    endpoint pointing back at this server.  The descriptor's `cmd`
    field carries the noetl:// ref URI bytes (same convention as
    Tickets in Phase A)."""
    port = _find_free_port()
    expected_rows = [
        {"id": 1, "username": "user_001", "password": "[REDACTED]"},
        {"id": 2, "username": "user_002", "password": "[REDACTED]"},
        {"id": 3, "username": "user_003", "password": "[REDACTED]"},
    ]

    async def fake_resolve(ref: Any) -> Any:
        assert isinstance(ref, str) and ref.startswith("noetl://")
        return {"data": {"columns": ["id", "username", "password"], "rows": expected_rows}}

    monkeypatch.setattr(
        "noetl.server.api.result.flight_server.default_store",
        type("StubStore", (), {"resolve": staticmethod(fake_resolve)}),
    )

    server = NoetlFlightServer(location=f"grpc://127.0.0.1:{port}")
    server.start_in_thread()
    _wait_until_listening(port)
    try:
        client = pyarrow_flight.connect(f"grpc://127.0.0.1:{port}")
        descriptor = pyarrow_flight.FlightDescriptor.for_command(
            b"noetl://execution/12345/result/big_select/abcd1234"
        )
        info = client.get_flight_info(descriptor)

        assert info.total_records == 3
        assert info.total_bytes > 0
        assert len(info.endpoints) == 1
        endpoint = info.endpoints[0]
        # The ticket the FlightInfo hands back is exactly the bytes
        # a client would submit to do_get directly — consumers with
        # a known ref URI can skip get_flight_info entirely.
        assert (
            bytes(endpoint.ticket.ticket)
            == b"noetl://execution/12345/result/big_select/abcd1234"
        )
        # Schema field names match the Python row dicts (DictionaryArrow
        # type inference falls back to Utf8 + Int64 here).
        assert info.schema.names == ["id", "username", "password"]
    finally:
        server.shutdown()


def test_flight_get_flight_info_rejects_path_descriptor(monkeypatch):
    """Phase C1 only supports Cmd-shaped descriptors.  Path-shaped
    descriptors raise so consumers see a clear error rather than a
    silent fallback."""
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
        with pytest.raises(
            (pyarrow_flight.FlightServerError, pyarrow_flight.FlightInternalError)
        ) as exc_info:
            client.get_flight_info(descriptor)
        assert "Cmd-shaped descriptor" in str(exc_info.value)
    finally:
        server.shutdown()


def test_flight_get_flight_info_non_tabular_raises_unavailable(monkeypatch):
    """Same fallback signal as do_get — non-tabular result → server
    raises FlightUnavailableError so the client falls back to HTTP."""
    port = _find_free_port()

    async def fake_resolve(ref: Any) -> Any:
        # Shell-tool shape: no rows.
        return {"stdout": "hello", "exit_code": 0}

    monkeypatch.setattr(
        "noetl.server.api.result.flight_server.default_store",
        type("StubStore", (), {"resolve": staticmethod(fake_resolve)}),
    )

    server = NoetlFlightServer(location=f"grpc://127.0.0.1:{port}")
    server.start_in_thread()
    _wait_until_listening(port)
    try:
        client = pyarrow_flight.connect(f"grpc://127.0.0.1:{port}")
        descriptor = pyarrow_flight.FlightDescriptor.for_command(
            b"noetl://execution/12345/result/shell_step/x"
        )
        with pytest.raises(pyarrow_flight.FlightUnavailableError):
            client.get_flight_info(descriptor)
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


# ---------------------------------------------------------------------------
# R-2.3 Phase C2.1 — Server-side TLS
# ---------------------------------------------------------------------------


def test_tls_construction_requires_both_cert_and_key():
    """tls_cert_path + tls_key_path must be set together — one without
    the other is a misconfiguration that would silently degrade to
    plaintext otherwise."""
    with pytest.raises(ValueError, match="must both be set or both be None"):
        NoetlFlightServer(
            location="grpc://0.0.0.0:8083",
            tls_cert_path="/etc/noetl/flight.crt",
            tls_key_path=None,
        )
    with pytest.raises(ValueError, match="must both be set or both be None"):
        NoetlFlightServer(
            location="grpc://0.0.0.0:8083",
            tls_cert_path=None,
            tls_key_path="/etc/noetl/flight.key",
        )


def test_tls_normalises_location_scheme_to_grpc_tls(tmp_path):
    """When TLS certs are present the location URL auto-upgrades from
    grpc:// to grpc+tls:// — pyarrow.flight uses the scheme as the
    signal to wrap the listener in OpenSSL.  Callers that already
    pass grpc+tls:// stay untouched."""
    cert = tmp_path / "flight.crt"
    key = tmp_path / "flight.key"
    cert.write_bytes(b"dummy")
    key.write_bytes(b"dummy")

    upgraded = NoetlFlightServer(
        location="grpc://0.0.0.0:8083",
        tls_cert_path=str(cert),
        tls_key_path=str(key),
    )
    assert upgraded.location == "grpc+tls://0.0.0.0:8083"

    passthrough = NoetlFlightServer(
        location="grpc+tls://0.0.0.0:8083",
        tls_cert_path=str(cert),
        tls_key_path=str(key),
    )
    assert passthrough.location == "grpc+tls://0.0.0.0:8083"


def test_plaintext_mode_keeps_grpc_scheme():
    """No TLS env → location URL stays grpc:// — kind default, no
    migration burden."""
    server = NoetlFlightServer(location="grpc://0.0.0.0:8083")
    assert server.location == "grpc://0.0.0.0:8083"
    assert server.tls_cert_path is None
    assert server.tls_key_path is None
    assert server._load_tls_certificates() is None


def test_tls_load_certificates_reads_pem_bytes(tmp_path):
    """_load_tls_certificates returns the on-disk cert + key as a
    single (cert_bytes, key_bytes) pair — FlightServerBase's wire
    shape for the tls_certificates= kwarg."""
    cert = tmp_path / "flight.crt"
    key = tmp_path / "flight.key"
    cert.write_bytes(b"-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----")
    key.write_bytes(b"-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----")

    server = NoetlFlightServer(
        location="grpc://0.0.0.0:8083",
        tls_cert_path=str(cert),
        tls_key_path=str(key),
    )
    certs = server._load_tls_certificates()
    assert certs is not None
    assert len(certs) == 1
    cert_bytes, key_bytes = certs[0]
    assert b"BEGIN CERTIFICATE" in cert_bytes
    assert b"BEGIN PRIVATE KEY" in key_bytes


def test_from_env_plaintext_default(monkeypatch):
    """Unset TLS env vars → plaintext server with the default
    location.  Same behaviour the kind manifest depends on."""
    monkeypatch.delenv("NOETL_FLIGHT_LOCATION", raising=False)
    monkeypatch.delenv("NOETL_FLIGHT_TLS_CERT", raising=False)
    monkeypatch.delenv("NOETL_FLIGHT_TLS_KEY", raising=False)
    server = NoetlFlightServer.from_env()
    assert server.location == "grpc://0.0.0.0:8083"
    assert server.tls_cert_path is None
    assert server.tls_key_path is None


def test_from_env_tls_pair(monkeypatch, tmp_path):
    """NOETL_FLIGHT_TLS_CERT + NOETL_FLIGHT_TLS_KEY → TLS-enabled
    server with grpc+tls:// scheme."""
    cert = tmp_path / "flight.crt"
    key = tmp_path / "flight.key"
    cert.write_bytes(b"dummy")
    key.write_bytes(b"dummy")

    monkeypatch.setenv("NOETL_FLIGHT_LOCATION", "grpc://0.0.0.0:8083")
    monkeypatch.setenv("NOETL_FLIGHT_TLS_CERT", str(cert))
    monkeypatch.setenv("NOETL_FLIGHT_TLS_KEY", str(key))
    server = NoetlFlightServer.from_env()
    assert server.location == "grpc+tls://0.0.0.0:8083"
    assert server.tls_cert_path == str(cert)
    assert server.tls_key_path == str(key)


def test_from_env_partial_tls_raises(monkeypatch, tmp_path):
    """NOETL_FLIGHT_TLS_CERT without KEY (or vice versa) → ValueError
    so a misconfigured pod fails fast rather than serving plaintext
    after the operator thought they'd enabled TLS."""
    cert = tmp_path / "flight.crt"
    cert.write_bytes(b"dummy")

    monkeypatch.setenv("NOETL_FLIGHT_TLS_CERT", str(cert))
    monkeypatch.delenv("NOETL_FLIGHT_TLS_KEY", raising=False)
    with pytest.raises(ValueError, match="must both be set or both be None"):
        NoetlFlightServer.from_env()


# ---------------------------------------------------------------------------
# R-2.3 Phase C2.3 — Bearer-token middleware
# ---------------------------------------------------------------------------


def test_parse_bearer_tokens_empty_returns_empty_set():
    """Empty / None input → empty set (no-auth mode)."""
    from noetl.server.api.result.flight_server import _parse_bearer_tokens

    assert _parse_bearer_tokens(None) == set()
    assert _parse_bearer_tokens("") == set()
    assert _parse_bearer_tokens("   ") == set()


def test_parse_bearer_tokens_splits_and_trims():
    """Comma-separated, trims whitespace, drops empty entries."""
    from noetl.server.api.result.flight_server import _parse_bearer_tokens

    assert _parse_bearer_tokens("alpha,beta") == {"alpha", "beta"}
    assert _parse_bearer_tokens("alpha , beta , ") == {"alpha", "beta"}
    assert _parse_bearer_tokens(", ,, alpha,,") == {"alpha"}


def test_bearer_tokens_none_means_no_auth():
    """Constructing without bearer_tokens leaves auth disabled."""
    server = NoetlFlightServer(location="grpc://0.0.0.0:8083")
    assert server.bearer_tokens is None
    assert server._build_middleware() is None


def test_bearer_tokens_empty_set_normalised_to_none():
    """Empty set ⇒ None (no-auth) — falsy values collapse to the
    same internal shape so the build path has one branch to check."""
    server = NoetlFlightServer(
        location="grpc://0.0.0.0:8083",
        bearer_tokens=set(),
    )
    assert server.bearer_tokens is None
    assert server._build_middleware() is None


def test_bearer_tokens_builds_middleware_factory():
    """Populated set ⇒ middleware mapping with `bearer-auth` key
    bound to a `ServerMiddlewareFactory`."""
    server = NoetlFlightServer(
        location="grpc://0.0.0.0:8083",
        bearer_tokens={"alpha", "beta"},
    )
    middleware = server._build_middleware()
    assert middleware is not None
    assert set(middleware.keys()) == {"bearer-auth"}
    factory = middleware["bearer-auth"]
    assert hasattr(factory, "start_call"), "expected a ServerMiddlewareFactory subclass"


def test_bearer_middleware_accepts_valid_token():
    """`Authorization: Bearer <token>` with a configured token →
    `start_call` returns None (accept; no per-call middleware)."""
    server = NoetlFlightServer(
        location="grpc://0.0.0.0:8083",
        bearer_tokens={"sk-test-valid"},
    )
    middleware = server._build_middleware()
    factory = middleware["bearer-auth"]
    result = factory.start_call(
        info=None,
        headers={"authorization": ["Bearer sk-test-valid"]},
    )
    assert result is None


def test_bearer_middleware_accepts_lowercase_bearer():
    """`bearer ` casing (gRPC-metadata frequently lowercases) is
    accepted."""
    server = NoetlFlightServer(
        location="grpc://0.0.0.0:8083",
        bearer_tokens={"sk-test"},
    )
    factory = server._build_middleware()["bearer-auth"]
    assert (
        factory.start_call(info=None, headers={"authorization": ["bearer sk-test"]})
        is None
    )


def test_bearer_middleware_rejects_missing_header(monkeypatch):
    """No `Authorization` header → `FlightUnauthenticatedError`."""
    server = NoetlFlightServer(
        location="grpc://0.0.0.0:8083",
        bearer_tokens={"sk-test"},
    )
    factory = server._build_middleware()["bearer-auth"]
    with pytest.raises(pyarrow_flight.FlightUnauthenticatedError):
        factory.start_call(info=None, headers={})


def test_bearer_middleware_rejects_wrong_token():
    """Wrong token → `FlightUnauthenticatedError`."""
    server = NoetlFlightServer(
        location="grpc://0.0.0.0:8083",
        bearer_tokens={"sk-test"},
    )
    factory = server._build_middleware()["bearer-auth"]
    with pytest.raises(pyarrow_flight.FlightUnauthenticatedError):
        factory.start_call(
            info=None,
            headers={"authorization": ["Bearer sk-wrong"]},
        )


def test_bearer_middleware_rejects_basic_auth():
    """Non-Bearer schemes (Basic, etc.) → `FlightUnauthenticatedError`
    even when a configured token happens to match the scheme value.
    Locks in that we only honor the `Bearer` scheme."""
    server = NoetlFlightServer(
        location="grpc://0.0.0.0:8083",
        bearer_tokens={"YWxwaGE6YmV0YQ=="},  # base64("alpha:beta")
    )
    factory = server._build_middleware()["bearer-auth"]
    with pytest.raises(pyarrow_flight.FlightUnauthenticatedError):
        factory.start_call(
            info=None,
            headers={"authorization": ["Basic YWxwaGE6YmV0YQ=="]},
        )


def test_bearer_middleware_token_rotation():
    """Multiple tokens in the set → any one of them accepted.
    Locks in the rotation pattern: deploy v2 with {v1, v2}, rotate
    clients, then drop v1."""
    server = NoetlFlightServer(
        location="grpc://0.0.0.0:8083",
        bearer_tokens={"old-token", "new-token"},
    )
    factory = server._build_middleware()["bearer-auth"]
    assert (
        factory.start_call(info=None, headers={"authorization": ["Bearer old-token"]})
        is None
    )
    assert (
        factory.start_call(info=None, headers={"authorization": ["Bearer new-token"]})
        is None
    )


def test_from_env_picks_up_bearer_tokens(monkeypatch):
    """`NOETL_FLIGHT_BEARER_TOKENS` populates the bearer_tokens set."""
    monkeypatch.delenv("NOETL_FLIGHT_LOCATION", raising=False)
    monkeypatch.delenv("NOETL_FLIGHT_TLS_CERT", raising=False)
    monkeypatch.delenv("NOETL_FLIGHT_TLS_KEY", raising=False)
    monkeypatch.setenv("NOETL_FLIGHT_BEARER_TOKENS", "tok-1, tok-2, tok-3")
    server = NoetlFlightServer.from_env()
    assert server.bearer_tokens == {"tok-1", "tok-2", "tok-3"}


def test_from_env_no_tokens_means_no_auth(monkeypatch):
    """Unset `NOETL_FLIGHT_BEARER_TOKENS` → bearer_tokens is None."""
    monkeypatch.delenv("NOETL_FLIGHT_LOCATION", raising=False)
    monkeypatch.delenv("NOETL_FLIGHT_TLS_CERT", raising=False)
    monkeypatch.delenv("NOETL_FLIGHT_TLS_KEY", raising=False)
    monkeypatch.delenv("NOETL_FLIGHT_BEARER_TOKENS", raising=False)
    server = NoetlFlightServer.from_env()
    assert server.bearer_tokens is None


def test_bearer_tokens_independent_of_tls(monkeypatch, tmp_path):
    """Auth + TLS are independently opt-in — bearer-on + plaintext
    is a valid combo (auth handled by a separate TLS terminator)."""
    monkeypatch.delenv("NOETL_FLIGHT_TLS_CERT", raising=False)
    monkeypatch.delenv("NOETL_FLIGHT_TLS_KEY", raising=False)
    monkeypatch.setenv("NOETL_FLIGHT_BEARER_TOKENS", "the-token")
    server = NoetlFlightServer.from_env()
    assert server.tls_cert_path is None
    assert server.bearer_tokens == {"the-token"}
    assert server.location.startswith("grpc://"), "no TLS, no scheme upgrade"
