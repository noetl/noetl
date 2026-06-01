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
    """

    def __init__(
        self,
        location: str = "grpc://0.0.0.0:8083",
        tls_cert_path: Optional[str] = None,
        tls_key_path: Optional[str] = None,
    ):
        if (tls_cert_path is None) != (tls_key_path is None):
            raise ValueError(
                "tls_cert_path and tls_key_path must both be set or both be None; "
                f"got cert={tls_cert_path!r}, key={tls_key_path!r}"
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

        TLS is opt-in: omit both env vars to keep the plaintext h2c
        mode the kind manifest ships.
        """
        import os

        location = os.getenv("NOETL_FLIGHT_LOCATION", default_location)
        cert = os.getenv("NOETL_FLIGHT_TLS_CERT") or None
        key = os.getenv("NOETL_FLIGHT_TLS_KEY") or None
        return cls(location=location, tls_cert_path=cert, tls_key_path=key)

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
        return _Server(location=outer.location, tls_certificates=tls_certs)

    def start_in_thread(self) -> None:
        """Spawn the Flight server in a daemon thread.  Returns immediately."""
        if self._thread is not None:
            return
        self._server = self._build_server()

        tls_mode = "tls" if self.tls_cert_path else "plaintext"

        def _run() -> None:
            try:
                logger.info(
                    "Arrow Flight server starting at %s (mode=%s, R-2.3)",
                    self.location,
                    tls_mode,
                )
                self._server.serve()
                logger.info("Arrow Flight server stopped (mode=%s)", tls_mode)
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
