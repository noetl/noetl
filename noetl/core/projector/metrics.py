"""Metrics helpers for standalone projector workers."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from typing import Any, Iterable, Mapping, Optional


class ProjectorMetrics:
    """Thread-safe counters for projector worker scrape output."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._values: dict[str, float] = {
            "notifications_total": 0.0,
            "events_extracted_total": 0.0,
            "events_owned_total": 0.0,
            "events_unowned_total": 0.0,
            "events_unshardable_total": 0.0,
            "projection_records_total": 0.0,
            "projection_stale_records_total": 0.0,
            "projection_errors_total": 0.0,
            "decode_errors_total": 0.0,
            "acknowledged_notifications_total": 0.0,
            "redelivery_requests_total": 0.0,
            "delayed_redelivery_requests_total": 0.0,
            "terminated_notifications_total": 0.0,
            "empty_or_unowned_notifications_total": 0.0,
            "errors_total": 0.0,
            "last_success_unixtime": 0.0,
            "last_error_unixtime": 0.0,
            "last_action_unixtime": 0.0,
            "last_ack_unixtime": 0.0,
            "last_redelivery_request_unixtime": 0.0,
            "last_termination_unixtime": 0.0,
            "last_redelivery_delay_seconds": 0.0,
            "last_batch_extracted_events": 0.0,
            "last_batch_events": 0.0,
            "last_batch_unowned_events": 0.0,
            "last_batch_unshardable_events": 0.0,
            "last_batch_projection_records": 0.0,
            "last_batch_stale_projection_records": 0.0,
            "last_projection_source_event_id": 0.0,
            "last_projection_event_time_watermark_unixtime": 0.0,
            "last_projection_projected_at_unixtime": 0.0,
            "last_projection_lag_milliseconds": 0.0,
            "max_projection_lag_milliseconds": 0.0,
        }

    def record_notification(
        self,
        *,
        extracted_events: int,
        owned_events: int,
        projection_records: int,
        unowned_events: int = 0,
        unshardable_events: int = 0,
        stale_projection_records: int = 0,
    ) -> None:
        now = time.time()
        with self._lock:
            self._values["notifications_total"] += 1.0
            self._values["events_extracted_total"] += float(max(0, extracted_events))
            self._values["events_owned_total"] += float(max(0, owned_events))
            self._values["events_unowned_total"] += float(max(0, unowned_events))
            self._values["events_unshardable_total"] += float(max(0, unshardable_events))
            self._values["projection_records_total"] += float(max(0, projection_records))
            self._values["projection_stale_records_total"] += float(max(0, stale_projection_records))
            self._values["last_success_unixtime"] = now
            self._values["last_batch_extracted_events"] = float(max(0, extracted_events))
            self._values["last_batch_events"] = float(max(0, owned_events))
            self._values["last_batch_unowned_events"] = float(max(0, unowned_events))
            self._values["last_batch_unshardable_events"] = float(max(0, unshardable_events))
            self._values["last_batch_projection_records"] = float(max(0, projection_records))
            self._values["last_batch_stale_projection_records"] = float(max(0, stale_projection_records))
            if owned_events <= 0:
                self._values["empty_or_unowned_notifications_total"] += 1.0

    def record_error(self) -> None:
        with self._lock:
            self._values["errors_total"] += 1.0
            self._values["projection_errors_total"] += 1.0
            self._values["last_error_unixtime"] = time.time()

    def record_decode_error(self) -> None:
        with self._lock:
            self._values["errors_total"] += 1.0
            self._values["decode_errors_total"] += 1.0
            self._values["last_error_unixtime"] = time.time()

    def record_message_action(self, action: str, delay_seconds: Optional[float] = None) -> None:
        now = time.time()
        with self._lock:
            if action == "ack":
                self._values["acknowledged_notifications_total"] += 1.0
                self._values["last_ack_unixtime"] = now
            elif action == "nak":
                self._values["redelivery_requests_total"] += 1.0
                self._values["last_redelivery_request_unixtime"] = now
                if delay_seconds is not None and delay_seconds > 0:
                    self._values["delayed_redelivery_requests_total"] += 1.0
                    self._values["last_redelivery_delay_seconds"] = float(delay_seconds)
                else:
                    self._values["last_redelivery_delay_seconds"] = 0.0
            elif action == "term":
                self._values["terminated_notifications_total"] += 1.0
                self._values["last_termination_unixtime"] = now
            else:
                return
            self._values["last_action_unixtime"] = now

    def record_projection_checkpoints(self, records: Iterable[Any]) -> None:
        with self._lock:
            for record in records:
                meta = getattr(record, "meta", None)
                meta = meta if isinstance(meta, Mapping) else {}
                source_event_id = _coerce_float(
                    meta.get("source_event_id") or getattr(record, "source_event_id", None)
                )
                event_watermark = _coerce_datetime_unixtime(meta.get("event_time_watermark"))
                projected_at = _coerce_datetime_unixtime(meta.get("projected_at"))
                lag_ms = _coerce_float(meta.get("projection_lag_ms"))

                if source_event_id is not None:
                    self._values["last_projection_source_event_id"] = source_event_id
                if event_watermark is not None:
                    self._values["last_projection_event_time_watermark_unixtime"] = event_watermark
                if projected_at is not None:
                    self._values["last_projection_projected_at_unixtime"] = projected_at
                if lag_ms is not None:
                    self._values["last_projection_lag_milliseconds"] = lag_ms
                    self._values["max_projection_lag_milliseconds"] = max(
                        self._values["max_projection_lag_milliseconds"],
                        lag_ms,
                    )

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return dict(self._values)

    def action_summary(self) -> dict[str, float]:
        with self._lock:
            acknowledged = self._values["acknowledged_notifications_total"]
            redelivery = self._values["redelivery_requests_total"]
            terminated = self._values["terminated_notifications_total"]
            total = acknowledged + redelivery + terminated
            return {
                "actions_total": total,
                "acknowledged_notifications_total": acknowledged,
                "redelivery_requests_total": redelivery,
                "delayed_redelivery_requests_total": self._values["delayed_redelivery_requests_total"],
                "terminated_notifications_total": terminated,
                "ack_ratio": acknowledged / total if total else 0.0,
                "redelivery_ratio": redelivery / total if total else 0.0,
                "termination_ratio": terminated / total if total else 0.0,
            }

    def batch_summary(self) -> dict[str, float]:
        with self._lock:
            extracted = self._values["last_batch_extracted_events"]
            owned = self._values["last_batch_events"]
            unowned = self._values["last_batch_unowned_events"]
            unshardable = self._values["last_batch_unshardable_events"]
            projection_records = self._values["last_batch_projection_records"]
            stale_projection_records = self._values["last_batch_stale_projection_records"]
            return {
                "extracted_events": extracted,
                "owned_events": owned,
                "unowned_events": unowned,
                "unshardable_events": unshardable,
                "projection_records": projection_records,
                "stale_projection_records": stale_projection_records,
                "owned_ratio": _safe_ratio(owned, extracted),
                "unowned_ratio": _safe_ratio(unowned, extracted),
                "unshardable_ratio": _safe_ratio(unshardable, extracted),
                "projection_record_ratio": _safe_ratio(projection_records, owned),
                "stale_projection_ratio": _safe_ratio(stale_projection_records, projection_records),
            }

    def error_summary(self) -> dict[str, float]:
        with self._lock:
            errors = self._values["errors_total"]
            decode_errors = self._values["decode_errors_total"]
            projection_errors = self._values["projection_errors_total"]
            return {
                "errors_total": errors,
                "decode_errors_total": decode_errors,
                "projection_errors_total": projection_errors,
                "decode_error_ratio": _safe_ratio(decode_errors, errors),
                "projection_error_ratio": _safe_ratio(projection_errors, errors),
                "last_error_unixtime": self._values["last_error_unixtime"],
            }


def render_projector_metrics(metrics: ProjectorMetrics, *, labels: Optional[Mapping[str, str]] = None) -> str:
    """Render projector metrics using Prometheus text exposition."""

    label_text = _format_labels(labels or {})
    snapshot = metrics.snapshot()
    lines = [
        "# HELP noetl_projector_notifications_total NATS notifications handled by this projector.",
        "# TYPE noetl_projector_notifications_total counter",
        f"noetl_projector_notifications_total{label_text} {snapshot['notifications_total']}",
        "# HELP noetl_projector_events_extracted_total Events extracted from projector notifications.",
        "# TYPE noetl_projector_events_extracted_total counter",
        f"noetl_projector_events_extracted_total{label_text} {snapshot['events_extracted_total']}",
        "# HELP noetl_projector_events_owned_total Events owned by this projector shard.",
        "# TYPE noetl_projector_events_owned_total counter",
        f"noetl_projector_events_owned_total{label_text} {snapshot['events_owned_total']}",
        "# HELP noetl_projector_events_unowned_total Events assigned to another projector shard.",
        "# TYPE noetl_projector_events_unowned_total counter",
        f"noetl_projector_events_unowned_total{label_text} {snapshot['events_unowned_total']}",
        "# HELP noetl_projector_events_unshardable_total Events without a valid shard key.",
        "# TYPE noetl_projector_events_unshardable_total counter",
        f"noetl_projector_events_unshardable_total{label_text} {snapshot['events_unshardable_total']}",
        "# HELP noetl_projector_projection_records_total Projection records written by this projector.",
        "# TYPE noetl_projector_projection_records_total counter",
        f"noetl_projector_projection_records_total{label_text} {snapshot['projection_records_total']}",
        "# HELP noetl_projector_projection_stale_records_total Projection records skipped because a newer version already exists.",
        "# TYPE noetl_projector_projection_stale_records_total counter",
        (
            "noetl_projector_projection_stale_records_total"
            f"{label_text} {snapshot['projection_stale_records_total']}"
        ),
        "# HELP noetl_projector_projection_errors_total Projector notification projection callback failures.",
        "# TYPE noetl_projector_projection_errors_total counter",
        f"noetl_projector_projection_errors_total{label_text} {snapshot['projection_errors_total']}",
        "# HELP noetl_projector_decode_errors_total Projector notification payload decode failures.",
        "# TYPE noetl_projector_decode_errors_total counter",
        f"noetl_projector_decode_errors_total{label_text} {snapshot['decode_errors_total']}",
        "# HELP noetl_projector_acknowledged_notifications_total Projector notifications ACKed after handling.",
        "# TYPE noetl_projector_acknowledged_notifications_total counter",
        (
            "noetl_projector_acknowledged_notifications_total"
            f"{label_text} {snapshot['acknowledged_notifications_total']}"
        ),
        "# HELP noetl_projector_redelivery_requests_total Projector notifications NAKed for redelivery.",
        "# TYPE noetl_projector_redelivery_requests_total counter",
        f"noetl_projector_redelivery_requests_total{label_text} {snapshot['redelivery_requests_total']}",
        "# HELP noetl_projector_delayed_redelivery_requests_total Projector notifications NAKed for delayed redelivery.",
        "# TYPE noetl_projector_delayed_redelivery_requests_total counter",
        (
            "noetl_projector_delayed_redelivery_requests_total"
            f"{label_text} {snapshot['delayed_redelivery_requests_total']}"
        ),
        "# HELP noetl_projector_terminated_notifications_total Projector notifications TERMed without redelivery.",
        "# TYPE noetl_projector_terminated_notifications_total counter",
        (
            "noetl_projector_terminated_notifications_total"
            f"{label_text} {snapshot['terminated_notifications_total']}"
        ),
        "# HELP noetl_projector_empty_or_unowned_notifications_total Notifications with no owned events.",
        "# TYPE noetl_projector_empty_or_unowned_notifications_total counter",
        (
            "noetl_projector_empty_or_unowned_notifications_total"
            f"{label_text} {snapshot['empty_or_unowned_notifications_total']}"
        ),
        "# HELP noetl_projector_errors_total Projector notification handling failures.",
        "# TYPE noetl_projector_errors_total counter",
        f"noetl_projector_errors_total{label_text} {snapshot['errors_total']}",
        "# HELP noetl_projector_last_success_unixtime Last successful notification handling time.",
        "# TYPE noetl_projector_last_success_unixtime gauge",
        f"noetl_projector_last_success_unixtime{label_text} {snapshot['last_success_unixtime']}",
        "# HELP noetl_projector_last_error_unixtime Last failed notification handling time.",
        "# TYPE noetl_projector_last_error_unixtime gauge",
        f"noetl_projector_last_error_unixtime{label_text} {snapshot['last_error_unixtime']}",
        "# HELP noetl_projector_last_action_unixtime Last projector subscriber terminal action time.",
        "# TYPE noetl_projector_last_action_unixtime gauge",
        f"noetl_projector_last_action_unixtime{label_text} {snapshot['last_action_unixtime']}",
        "# HELP noetl_projector_last_ack_unixtime Last projector notification ACK time.",
        "# TYPE noetl_projector_last_ack_unixtime gauge",
        f"noetl_projector_last_ack_unixtime{label_text} {snapshot['last_ack_unixtime']}",
        "# HELP noetl_projector_last_redelivery_request_unixtime Last projector notification NAK time.",
        "# TYPE noetl_projector_last_redelivery_request_unixtime gauge",
        (
            "noetl_projector_last_redelivery_request_unixtime"
            f"{label_text} {snapshot['last_redelivery_request_unixtime']}"
        ),
        "# HELP noetl_projector_last_termination_unixtime Last projector notification TERM time.",
        "# TYPE noetl_projector_last_termination_unixtime gauge",
        f"noetl_projector_last_termination_unixtime{label_text} {snapshot['last_termination_unixtime']}",
        "# HELP noetl_projector_last_redelivery_delay_seconds Last requested projector redelivery delay.",
        "# TYPE noetl_projector_last_redelivery_delay_seconds gauge",
        f"noetl_projector_last_redelivery_delay_seconds{label_text} {snapshot['last_redelivery_delay_seconds']}",
        "# HELP noetl_projector_last_batch_events Owned events in the last handled notification.",
        "# TYPE noetl_projector_last_batch_events gauge",
        f"noetl_projector_last_batch_events{label_text} {snapshot['last_batch_events']}",
        "# HELP noetl_projector_last_batch_extracted_events Events extracted from the last handled notification.",
        "# TYPE noetl_projector_last_batch_extracted_events gauge",
        f"noetl_projector_last_batch_extracted_events{label_text} {snapshot['last_batch_extracted_events']}",
        "# HELP noetl_projector_last_batch_unowned_events Events assigned to other shards in the last handled notification.",
        "# TYPE noetl_projector_last_batch_unowned_events gauge",
        f"noetl_projector_last_batch_unowned_events{label_text} {snapshot['last_batch_unowned_events']}",
        "# HELP noetl_projector_last_batch_unshardable_events Events without valid shard keys in the last handled notification.",
        "# TYPE noetl_projector_last_batch_unshardable_events gauge",
        (
            "noetl_projector_last_batch_unshardable_events"
            f"{label_text} {snapshot['last_batch_unshardable_events']}"
        ),
        "# HELP noetl_projector_last_batch_projection_records Projection records from the last handled notification.",
        "# TYPE noetl_projector_last_batch_projection_records gauge",
        f"noetl_projector_last_batch_projection_records{label_text} {snapshot['last_batch_projection_records']}",
        "# HELP noetl_projector_last_batch_stale_projection_records Stale projection records from the last handled notification.",
        "# TYPE noetl_projector_last_batch_stale_projection_records gauge",
        (
            "noetl_projector_last_batch_stale_projection_records"
            f"{label_text} {snapshot['last_batch_stale_projection_records']}"
        ),
        "# HELP noetl_projector_last_projection_source_event_id Last projected source event id.",
        "# TYPE noetl_projector_last_projection_source_event_id gauge",
        f"noetl_projector_last_projection_source_event_id{label_text} {snapshot['last_projection_source_event_id']}",
        "# HELP noetl_projector_last_projection_event_time_watermark_unixtime Last projected event-time watermark.",
        "# TYPE noetl_projector_last_projection_event_time_watermark_unixtime gauge",
        (
            "noetl_projector_last_projection_event_time_watermark_unixtime"
            f"{label_text} {snapshot['last_projection_event_time_watermark_unixtime']}"
        ),
        "# HELP noetl_projector_last_projection_projected_at_unixtime Last projector write timestamp.",
        "# TYPE noetl_projector_last_projection_projected_at_unixtime gauge",
        (
            "noetl_projector_last_projection_projected_at_unixtime"
            f"{label_text} {snapshot['last_projection_projected_at_unixtime']}"
        ),
        "# HELP noetl_projector_last_projection_lag_milliseconds Latest projection lag from event watermark to write time.",
        "# TYPE noetl_projector_last_projection_lag_milliseconds gauge",
        f"noetl_projector_last_projection_lag_milliseconds{label_text} {snapshot['last_projection_lag_milliseconds']}",
        "# HELP noetl_projector_max_projection_lag_milliseconds Max observed projection lag since process start.",
        "# TYPE noetl_projector_max_projection_lag_milliseconds gauge",
        f"noetl_projector_max_projection_lag_milliseconds{label_text} {snapshot['max_projection_lag_milliseconds']}",
    ]
    return "\n".join(lines) + "\n"


def start_projector_metrics_server(
    metrics: ProjectorMetrics,
    *,
    host: str,
    port: int,
    labels: Optional[Mapping[str, str]] = None,
) -> ThreadingHTTPServer:
    """Start a lightweight `/metrics` HTTP server in a daemon thread."""

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
            body = render_projector_metrics(metrics, labels=labels).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer((host, port), _Handler)
    thread = Thread(target=server.serve_forever, name="noetl-projector-metrics", daemon=True)
    thread.start()
    return server


def _format_labels(labels: Mapping[str, str]) -> str:
    filtered = {key: value for key, value in labels.items() if value}
    if not filtered:
        return ""
    body = ",".join(f'{key}="{_escape_label(value)}"' for key, value in sorted(filtered.items()))
    return "{" + body + "}"


def _escape_label(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _safe_ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _coerce_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_datetime_unixtime(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


__all__ = [
    "ProjectorMetrics",
    "render_projector_metrics",
    "start_projector_metrics_server",
]
