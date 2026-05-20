"""Lightweight metrics endpoint for standalone NoETL workers."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Mapping

from noetl.core.storage import default_store
from noetl.server.metrics import append_storage_ipc_metrics


def render_worker_metrics(*, worker_id: str, labels: Mapping[str, str] | None = None) -> str:
    """Render worker-local counters using Prometheus text exposition."""
    metric_labels = {"worker_id": worker_id}
    metric_labels.update(labels or {})

    lines = [
        "# HELP noetl_worker_up NoETL worker up status",
        "# TYPE noetl_worker_up gauge",
        f"noetl_worker_up{{worker_id=\"{_escape_label(worker_id)}\"}} 1",
    ]
    append_storage_ipc_metrics(lines, default_store.ipc_stats(), labels=metric_labels)
    return "\n".join(lines) + "\n"


def start_worker_metrics_server(
    *,
    worker_id: str,
    host: str,
    port: int,
    labels: Mapping[str, str] | None = None,
) -> ThreadingHTTPServer:
    """Start a daemon `/metrics` HTTP server for this worker process."""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"ok\n")
                return
            if self.path != "/metrics":
                self.send_response(404)
                self.end_headers()
                return
            body = render_worker_metrics(worker_id=worker_id, labels=labels).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer((host, port), _Handler)
    thread = Thread(target=server.serve_forever, name="noetl-worker-metrics", daemon=True)
    thread.start()
    return server


def _escape_label(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


__all__ = ["render_worker_metrics", "start_worker_metrics_server"]
