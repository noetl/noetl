"""Arrow Flight gRPC endpoint for the noetl result store (R-2.3).

This module exposes a `pyarrow.flight.FlightServerBase` subclass that
serves the same data as the HTTP `GET /api/result/resolve?ref=...`
endpoint, but as an Arrow IPC stream over gRPC.

## Why Arrow Flight

The R-2.1 cross-node durable path ships tabular results through
`/api/result/resolve` as JSON.  For tabular tool outputs (DuckDB /
Postgres / Snowflake rowsets) this round-trips through:

    rows (in-memory)  ── server.put_result ──>  default_store.put
                                                      |
                                                      v
                                  rows ── JSON serialize ── tier write
                                  ↑
                                  └── server resolves ── JSON deserialize
                                                      |
                                                      v
                              Rust worker / Python consumer JSON-parses
                                              back to rows

For R-2.2 columnar tool outputs the worker already stages Arrow IPC
bytes in shm; the durable path however falls back to JSON because the
HTTP endpoint doesn't speak Arrow.

Arrow Flight closes that gap.  A consumer that knows it wants tabular
data calls `pyarrow.flight.connect(...).do_get(Ticket(ref_uri))`,
the server reads the stored data via `default_store.resolve`, encodes
it once via `rows_to_arrow_ipc`, and streams the IPC bytes back.  The
consumer reads with `RecordBatchStreamReader` — zero-copy, columnar.

## Wire format

- **Ticket**: the `noetl://execution/<eid>/result/<step>/<id>` URI as
  raw bytes.  Consumers already have it from `result.reference.ref`
  on the call.done event — no separate lookup needed.
- **DoGet response**: Arrow IPC stream of the materialized RecordBatch.
  For tabular results → encoded via `rows_to_arrow_ipc` (the same
  function the worker uses for the shm fast path, so the wire format
  is identical regardless of producer).
- **Non-tabular results**: returned via `FlightError::Unimplemented`
  for Phase A — consumers fall back to `/api/result/resolve` HTTP.

## Boundary discipline

This endpoint is a thin Flight wrapper around the existing
`default_store.resolve`.  All scrubbing + tier dispatch + auth
happens in the underlying store; the Flight server adds no new
trust boundary.  The cluster-internal gRPC port (default 8083) is
not exposed publicly — same trust model as the existing
`/api/result/resolve`.

## R-2.3 follow-up scope

Phase A (this module):
  - `do_get(ticket)` for tabular results.
  - Single in-cluster endpoint; no `FlightInfo` indirection yet.
  - Spawned alongside the FastAPI server in `app.py`'s lifespan.

Phase B (deferred):
  - Rust consumer via `arrow-flight` crate in noetl-worker.
  - Benchmark vs HTTP/JSON path.

Phase C (deferred):
  - Multi-endpoint `FlightInfo` for sharded result tiers.
  - mTLS + token auth for non-cluster-internal callers.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Optional

from noetl.core.storage import default_store
from noetl.core.storage.arrow_ipc import ARROW_STREAM_MEDIA_TYPE, rows_to_arrow_ipc

logger = logging.getLogger(__name__)


def _extract_rows(data: Any) -> Optional[list[dict[str, Any]]]:
    """Try to pull a list-of-dict rowset out of a resolved result.

    Accepts the two shapes the worker emits:
    - **wrapped**: ``{"columns": [...], "rows": [{...}, ...]}``
    - **nested under data**: ``{"data": {"columns": [...], "rows": [...]}}``

    Returns ``None`` if the data doesn't have a tabular shape, signalling
    to ``do_get`` that the consumer should fall back to the HTTP JSON path.
    """
    if not isinstance(data, dict):
        return None

    payload = data
    if "rows" not in payload:
        nested = payload.get("data")
        if isinstance(nested, dict) and "rows" in nested:
            payload = nested
        else:
            return None

    rows = payload.get("rows")
    if not isinstance(rows, list):
        return None
    # Row-array shape (e.g. DuckDB as_objects=False) — would need to
    # combine with `columns`, but we don't support that in Phase A.
    if rows and not isinstance(rows[0], dict):
        return None
    return rows  # type: ignore[return-value]


def _parse_bearer_tokens(raw: Optional[str]) -> set[str]:
    """Parse a comma-separated list of bearer tokens into a set.

    Empty / None input returns an empty set (no-auth mode).  Empty
    entries after splitting are dropped — callers can use trailing
    commas + whitespace without surprises.
    """
    if not raw:
        return set()
    return {t.strip() for t in raw.split(",") if t.strip()}


class NoetlFlightServer:
    """Arrow Flight gRPC server for result-store reads.

    Wraps `pyarrow.flight.FlightServerBase`.  Lazy-imported here so
    the noetl-server can start even on a host where pyarrow.flight
    is broken (it should be available wherever pyarrow is, but
    defensive imports keep startup robust).

    Start with ``server.start_in_thread()``; stop with
    ``server.shutdown()``.  Designed to run alongside the FastAPI
    process — gRPC and HTTP listen on different ports.

    ## TLS mode (R-2.3 Phase C2.1)

    Pass ``tls_cert_path`` + ``tls_key_path`` (or the env pair
    ``NOETL_FLIGHT_TLS_CERT`` + ``NOETL_FLIGHT_TLS_KEY``, see
    :py:meth:`from_env`) to terminate TLS at the Flight gRPC port.
    The server presents the cert to every connecting client; the
    location URL automatically switches from ``grpc://`` to
    ``grpc+tls://`` so consumers receive a single source of truth
    about the wire protocol from a future ``ListEndpoints`` call.

    When both ``tls_cert_path`` and ``tls_key_path`` are unset the
    server keeps the existing plaintext h2c mode — same default
    behaviour the kind manifest ships, no migration burden.

    Client-certificate validation (mTLS) is reserved for Phase C2.4.

    ## Bearer-token auth (R-2.3 Phase C2.3)

    Pass ``bearer_tokens`` (a set of valid token strings) — or the
    env ``NOETL_FLIGHT_BEARER_TOKENS`` (comma-separated set, see
    :py:meth:`from_env`) — to require an ``Authorization: Bearer
    <token>`` header on every Flight call.  A request whose token
    isn't in the configured set raises ``FlightUnauthenticatedError``
    before reaching ``do_get`` / ``get_flight_info``.

    Tokens are a **set** rather than a single value so an operator
    can rotate without downtime: deploy v2 with both v1 + v2 valid,
    rotate clients, then drop v1.  Empty / unset → no auth (the
    Phase A default; same trust boundary as the HTTP
    ``/api/result/resolve`` endpoint).

    Auth is independent of TLS: bearer auth + plaintext is fine for
    in-cluster deployments behind a separate TLS terminator; bearer
    auth + TLS is the typical externally-exposed shape.

    Per [`agents/rules/execution-model.md`][exec] the server-side
    *set of valid tokens* is policy data (env / configmap / k8s
    Secret); the *token a client sends* is a business-logic
    credential and belongs in the NoETL keychain referenced by alias
    from the playbook step.

    [exec]: https://github.com/noetl/ai-meta/blob/main/agents/rules/execution-model.md

    ## mTLS (R-2.3 Phase C2.4)

    Pass ``client_ca_path`` — or the env ``NOETL_FLIGHT_CLIENT_CA``
    — to require client-cert validation on every Flight call
    (mutual TLS).  The server then refuses connections that don't
    present a cert chaining to the configured CA.  Requires TLS
    to be active (i.e. ``tls_cert_path`` + ``tls_key_path`` set);
    enabling mTLS without server TLS raises ``ValueError`` at
    construction.

    mTLS stacks on top of bearer-token auth — both run on the same
    request.  A typical externally-exposed deployment turns on
    server TLS + mTLS + bearer.  Internal deployments may stay on
    bearer + plaintext or server-TLS-only.
    """

    def __init__(
        self,
        location: str = "grpc://0.0.0.0:8083",
        tls_cert_path: Optional[str] = None,
        tls_key_path: Optional[str] = None,
        bearer_tokens: Optional[set[str]] = None,
        client_ca_path: Optional[str] = None,
    ):
        if (tls_cert_path is None) != (tls_key_path is None):
            raise ValueError(
                "tls_cert_path and tls_key_path must both be set or both be None; "
                f"got cert={tls_cert_path!r}, key={tls_key_path!r}"
            )
        if client_ca_path is not None and tls_cert_path is None:
            # mTLS without server TLS is a misconfiguration — there's no
            # TLS channel to mutually authenticate inside.  Fail fast.
            raise ValueError(
                "client_ca_path requires server TLS to be active "
                "(tls_cert_path + tls_key_path); got client_ca_path="
                f"{client_ca_path!r} but no server cert"
            )
        # When TLS is active, the location URL must use the
        # `grpc+tls://` scheme so pyarrow.flight knows to wrap the
        # listening socket in OpenSSL.  We accept callers passing
        # either scheme + normalise here.
        if tls_cert_path is not None and location.startswith("grpc://"):
            location = "grpc+tls://" + location[len("grpc://") :]
        self.location = location
        self.tls_cert_path = tls_cert_path
        self.tls_key_path = tls_key_path
        self.client_ca_path = client_ca_path
        # Empty set + None both mean "no auth".  Internally we keep
        # `None` to make the no-auth code path explicit.
        self.bearer_tokens: Optional[set[str]] = (
            bearer_tokens if bearer_tokens else None
        )
        self._server: Any = None  # pyarrow.flight.FlightServerBase instance
        self._thread: Optional[threading.Thread] = None
        self._serve_exception: Optional[BaseException] = None

    @classmethod
    def from_env(cls, default_location: str = "grpc://0.0.0.0:8083") -> "NoetlFlightServer":
        """Construct from environment variables.

        Reads:
        - ``NOETL_FLIGHT_LOCATION`` — listening location (default
          plaintext on 0.0.0.0:8083).  When ``NOETL_FLIGHT_TLS_CERT`` is
          set the scheme auto-upgrades to ``grpc+tls://``.
        - ``NOETL_FLIGHT_TLS_CERT`` — path to PEM-encoded server cert.
        - ``NOETL_FLIGHT_TLS_KEY`` — path to PEM-encoded private key.
        - ``NOETL_FLIGHT_BEARER_TOKENS`` — comma-separated set of
          accepted bearer tokens.  Unset → no auth.  Use a set
          rather than a single value to rotate without downtime.
        - ``NOETL_FLIGHT_CLIENT_CA`` (R-2.3 Phase C2.4) — path to a
          PEM-encoded client-CA bundle.  When set, the server
          requires + validates a client certificate (mTLS).
          Requires TLS to be active; mTLS-without-TLS raises
          ``ValueError`` at startup.

        TLS + bearer + mTLS are independently opt-in: omit all four
        TLS/auth env vars to keep the plaintext + no-auth mode the
        kind manifest ships.
        """
        import os

        location = os.getenv("NOETL_FLIGHT_LOCATION", default_location)
        cert = os.getenv("NOETL_FLIGHT_TLS_CERT") or None
        key = os.getenv("NOETL_FLIGHT_TLS_KEY") or None
        tokens = _parse_bearer_tokens(os.getenv("NOETL_FLIGHT_BEARER_TOKENS"))
        client_ca = os.getenv("NOETL_FLIGHT_CLIENT_CA") or None
        return cls(
            location=location,
            tls_cert_path=cert,
            tls_key_path=key,
            bearer_tokens=tokens or None,
            client_ca_path=client_ca,
        )

    def _load_tls_certificates(self) -> Optional[list[tuple[bytes, bytes]]]:
        """Read the cert + key from disk as bytes for FlightServerBase.

        Returns ``None`` when TLS is not configured (plaintext mode).
        """
        if self.tls_cert_path is None or self.tls_key_path is None:
            return None
        with open(self.tls_cert_path, "rb") as cf:
            cert_bytes = cf.read()
        with open(self.tls_key_path, "rb") as kf:
            key_bytes = kf.read()
        # FlightServerBase accepts a list of (cert, key) pairs — one
        # entry per listening location.  Phase C2.1 binds a single
        # location.
        return [(cert_bytes, key_bytes)]

    def _load_client_ca(self) -> Optional[bytes]:
        """Read the client-CA PEM bundle for mTLS (Phase C2.4).

        Returns ``None`` when mTLS is not configured.  Constructor
        already guarantees the CA path is only set when server TLS
        is active, so the caller doesn't have to re-check.
        """
        if self.client_ca_path is None:
            return None
        with open(self.client_ca_path, "rb") as f:
            return f.read()

    def _build_middleware(self) -> Optional[dict[str, Any]]:
        """Construct the `pyarrow.flight` middleware mapping.

        Phase C2.3 adds a single bearer-token validator middleware
        when ``self.bearer_tokens`` is set.  No-auth mode (empty /
        None) returns ``None`` and ``FlightServerBase`` runs without
        any per-call middleware.
        """
        if not self.bearer_tokens:
            return None
        import pyarrow.flight as flight

        tokens = self.bearer_tokens

        class BearerTokenMiddlewareFactory(flight.ServerMiddlewareFactory):
            """Validates an incoming `Authorization: Bearer <token>`
            header against the configured token set.

            Returns ``None`` (no per-call middleware needed) on
            success; raises ``FlightUnauthenticatedError`` on missing
            or invalid token — pyarrow.flight surfaces that as a
            gRPC `UNAUTHENTICATED` status to the client.

            Header lookup is case-insensitive per HTTP/2 spec
            (`grpc-metadata` is always lowercase on the wire) and
            tolerates the `Bearer ` prefix in either canonical or
            lowercased form.
            """

            def start_call(self, info: Any, headers: Any) -> Optional[Any]:
                # `headers` is a multi-valued mapping (`dict[str, list[str]]`).
                # The actual key shape pyarrow.flight produces is
                # lowercased per HTTP/2 / gRPC convention.
                auth_values: list[str] = []
                # Try a few common casings to be robust against
                # transport differences.
                for key in ("authorization", "Authorization"):
                    if key in headers:
                        v = headers[key]
                        if isinstance(v, (list, tuple)):
                            auth_values.extend(v)
                        else:
                            auth_values.append(v)

                for value in auth_values:
                    # Tolerate `Bearer <token>` + `bearer <token>` casings.
                    parts = value.split(None, 1)
                    if len(parts) == 2 and parts[0].lower() == "bearer":
                        token = parts[1].strip()
                        if token in tokens:
                            return None  # accept; no per-call middleware

                raise flight.FlightUnauthenticatedError(
                    "Missing or invalid bearer token; expected "
                    "Authorization: Bearer <token> with a token from "
                    "NOETL_FLIGHT_BEARER_TOKENS."
                )

        return {"bearer-auth": BearerTokenMiddlewareFactory()}

    def _build_server(self) -> Any:
        """Construct the pyarrow.flight server.  Lazy-imported."""
        import pyarrow.flight as flight

        outer = self

        class _Server(flight.FlightServerBase):
            def do_get(self, context: Any, ticket: Any) -> Any:
                ref_uri = ticket.ticket.decode("utf-8")
                logger.debug("Flight do_get: ref=%s", ref_uri)
                # Run the async resolve on the store's event loop —
                # FlightServerBase.do_get is called on a worker thread,
                # so we use asyncio.run_coroutine_threadsafe via a
                # newly-created loop (default_store.resolve is async).
                # This keeps the Flight server independent of the
                # FastAPI app's loop.
                loop = asyncio.new_event_loop()
                try:
                    data = loop.run_until_complete(default_store.resolve(ref_uri))
                finally:
                    loop.close()

                rows = _extract_rows(data)
                if rows is None:
                    raise flight.FlightUnavailableError(
                        f"Flight do_get only serves tabular results; ref={ref_uri} "
                        "has no row data.  Consumer should fall back to HTTP "
                        "/api/result/resolve."
                    )

                payload, _digest, _row_count = rows_to_arrow_ipc(rows)

                # Stream the IPC bytes back.  RecordBatchStream reads
                # from a pyarrow Buffer / file-like, so we wrap the
                # already-encoded bytes.
                import pyarrow as pa
                buffer = pa.py_buffer(payload)
                reader = pa.ipc.open_stream(buffer)
                return flight.RecordBatchStream(reader)

            def list_actions(self, context: Any) -> list[Any]:
                return []

            def list_flights(self, context: Any, criteria: Any) -> Any:
                return iter([])

            def get_flight_info(self, context: Any, descriptor: Any) -> Any:
                # R-2.3 Phase C1: return a FlightInfo summary so the
                # consumer can read schema + row count without
                # materialising the full payload.  Useful for clients
                # that want to size buffers, pick a backend, or skip
                # the fetch entirely for non-tabular refs.
                #
                # Wire convention: the descriptor's `cmd` field carries
                # the same `noetl://execution/<eid>/result/<step>/<id>`
                # URI bytes the Ticket uses (Phase A).  Path-shaped
                # descriptors aren't supported in Phase C1.
                if not getattr(descriptor, "command", None):
                    raise flight.FlightServerError(
                        "FlightInfo requires a Cmd-shaped descriptor whose "
                        "command bytes are the noetl:// ref URI.  Path-"
                        "shaped descriptors are not supported in Phase C1."
                    )
                ref_uri = bytes(descriptor.command).decode("utf-8", errors="replace")
                logger.debug("Flight get_flight_info: ref=%s", ref_uri)

                loop = asyncio.new_event_loop()
                try:
                    data = loop.run_until_complete(default_store.resolve(ref_uri))
                finally:
                    loop.close()

                rows = _extract_rows(data)
                if rows is None:
                    # Same signal Phase A do_get raises for non-
                    # tabular refs.  Consumers fall back to HTTP.
                    raise flight.FlightUnavailableError(
                        f"FlightInfo lookup found a non-tabular result for "
                        f"ref={ref_uri}; consumer should fall back to HTTP "
                        f"/api/result/resolve."
                    )

                # Encode a sample to extract the Arrow schema +
                # row_count without paying the full materialisation
                # cost twice — `rows_to_arrow_ipc` returns
                # (payload, _digest, row_count) AND the FlightInfo
                # carries the schema bytes inline, so we run the same
                # encode here that do_get would.  For multi-MB results
                # a future optimisation can compute the schema from
                # rows[:1] and persist row_count metadata in the store
                # to skip the full encode.
                import pyarrow as pa
                payload, _digest, row_count = rows_to_arrow_ipc(rows)
                with pa.ipc.open_stream(payload) as reader:
                    schema = reader.schema

                # Single endpoint pointing back at this server.  The
                # ticket is the same bytes the consumer would submit
                # to do_get directly — clients with a known ref URI
                # can skip get_flight_info and call do_get straight.
                endpoint = flight.FlightEndpoint(
                    ticket=flight.Ticket(ref_uri.encode("utf-8")),
                    locations=[outer.location],
                )
                return flight.FlightInfo(
                    schema=schema,
                    descriptor=descriptor,
                    endpoints=[endpoint],
                    total_records=row_count,
                    total_bytes=len(payload),
                )

        # TLS certs (Phase C2.1) — None in plaintext mode, otherwise
        # the single (cert, key) pair loaded from disk.
        tls_certs = outer._load_tls_certificates()
        # Auth middleware (Phase C2.3) — None when bearer-tokens is
        # empty / unset.
        middleware = outer._build_middleware()
        # Client CA bundle (Phase C2.4) — None when mTLS disabled;
        # otherwise pass with `verify_client=True` so pyarrow.flight
        # demands a client cert chaining to the bundle.
        client_ca = outer._load_client_ca()
        kwargs: dict[str, Any] = {
            "location": outer.location,
            "tls_certificates": tls_certs,
        }
        if middleware is not None:
            kwargs["middleware"] = middleware
        if client_ca is not None:
            kwargs["verify_client"] = True
            kwargs["root_certificates"] = client_ca
        return _Server(**kwargs)

    def start_in_thread(self) -> None:
        """Spawn the Flight server in a daemon thread.  Returns immediately."""
        if self._thread is not None:
            return
        self._server = self._build_server()

        # mTLS (Phase C2.4) reads as a third independent mode on
        # top of TLS — when on, server-tls is also necessarily on.
        if self.client_ca_path:
            tls_mode = "mtls"
        elif self.tls_cert_path:
            tls_mode = "tls"
        else:
            tls_mode = "plaintext"
        auth_mode = (
            f"bearer({len(self.bearer_tokens)})"
            if self.bearer_tokens
            else "none"
        )

        def _run() -> None:
            try:
                logger.info(
                    "Arrow Flight server starting at %s (tls=%s, auth=%s, R-2.3)",
                    self.location,
                    tls_mode,
                    auth_mode,
                )
                self._server.serve()
                logger.info(
                    "Arrow Flight server stopped (tls=%s, auth=%s)",
                    tls_mode,
                    auth_mode,
                )
            except BaseException as exc:  # noqa: BLE001
                logger.exception("Arrow Flight server crashed: %s", exc)
                self._serve_exception = exc

        self._thread = threading.Thread(
            target=_run,
            name="noetl-arrow-flight",
            daemon=True,
        )
        self._thread.start()

    def shutdown(self) -> None:
        """Gracefully stop the Flight server + join the thread."""
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Flight server shutdown error: %s", exc)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        if self._serve_exception is not None:
            logger.warning(
                "Arrow Flight server exited with exception: %s",
                self._serve_exception,
            )


__all__ = [
    "NoetlFlightServer",
    "ARROW_STREAM_MEDIA_TYPE",
]
