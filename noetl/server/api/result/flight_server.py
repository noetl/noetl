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
    """

    def __init__(self, location: str = "grpc://0.0.0.0:8083"):
        self.location = location
        self._server: Any = None  # pyarrow.flight.FlightServerBase instance
        self._thread: Optional[threading.Thread] = None
        self._serve_exception: Optional[BaseException] = None

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
                # Phase A: we don't expose flights by listing; consumers
                # already have the ref URI from `result.reference.ref`.
                # Raise as FlightServerError — pyarrow.flight in this
                # version doesn't ship an `Unimplemented` variant, but
                # the message + the FlightServerError type are enough
                # for clients to distinguish "not supported" from a
                # transient outage.
                raise flight.FlightServerError(
                    "FlightInfo lookup is not implemented in Phase A.  "
                    "Consumers submit Tickets directly to DoGet using the "
                    "noetl:// URI from `result.reference.ref` on the "
                    "call.done event."
                )

        return _Server(location=outer.location)

    def start_in_thread(self) -> None:
        """Spawn the Flight server in a daemon thread.  Returns immediately."""
        if self._thread is not None:
            return
        self._server = self._build_server()

        def _run() -> None:
            try:
                logger.info(
                    "Arrow Flight server starting at %s (R-2.3 Phase A)",
                    self.location,
                )
                self._server.serve()
                logger.info("Arrow Flight server stopped")
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
