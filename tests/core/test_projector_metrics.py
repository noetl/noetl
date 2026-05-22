from __future__ import annotations

import json
from types import SimpleNamespace
from urllib.request import urlopen


def test_projector_metrics_render_prometheus_labels():
    from noetl.core.projector.metrics import ProjectorMetrics, render_projector_metrics

    metrics = ProjectorMetrics()
    metrics.record_notification(
        extracted_events=3,
        owned_events=2,
        unowned_events=1,
        unshardable_events=0,
        stale_projection_records=1,
        projection_records=1,
    )

    body = render_projector_metrics(
        metrics,
        labels={
            "shard_id": "noetl-projector-0",
            "shard_index": "0",
            "shard_count": "2",
            "consumer": "consumer-a",
            "stream": "NOETL_EVENTS",
            "subject": "noetl.events.>",
        },
    )

    assert 'consumer="consumer-a"' in body
    assert 'shard_count="2"' in body
    assert 'shard_id="noetl-projector-0"' in body
    assert 'shard_index="0"' in body
    assert 'stream="NOETL_EVENTS"' in body
    assert 'subject="noetl.events.>"' in body
    assert "noetl_projector_notifications_total" in body
    assert "noetl_projector_events_extracted_total" in body
    assert "noetl_projector_events_owned_total" in body
    assert "noetl_projector_events_unowned_total" in body
    assert "noetl_projector_events_unshardable_total" in body
    assert "noetl_projector_projection_records_total" in body
    assert "noetl_projector_projection_stale_records_total" in body
    assert "noetl_projector_projection_errors_total" in body
    assert "noetl_projector_decode_errors_total" in body
    assert "noetl_projector_acknowledged_notifications_total" in body
    assert "noetl_projector_redelivery_requests_total" in body
    assert "noetl_projector_delayed_redelivery_requests_total" in body
    assert "noetl_projector_terminated_notifications_total" in body
    assert "noetl_projector_last_action_unixtime" in body
    assert "noetl_projector_last_ack_unixtime" in body
    assert "noetl_projector_last_redelivery_request_unixtime" in body
    assert "noetl_projector_last_termination_unixtime" in body
    assert "noetl_projector_last_redelivery_delay_seconds" in body
    assert "noetl_projector_last_batch_extracted_events" in body
    assert "noetl_projector_last_batch_unowned_events" in body
    assert "noetl_projector_last_batch_unshardable_events" in body
    assert "noetl_projector_last_batch_stale_projection_records" in body
    assert "noetl_projector_frame_projection_records_total" in body
    assert "noetl_projector_frame_projection_stale_records_total" in body
    assert "noetl_projector_last_batch_frame_projection_records" in body
    assert "noetl_projector_last_batch_frame_stale_projection_records" in body
    assert " 1.0" in body

    snapshot = metrics.snapshot()
    assert snapshot["last_batch_extracted_events"] == 3
    assert snapshot["last_batch_events"] == 2
    assert snapshot["last_batch_unowned_events"] == 1
    assert snapshot["last_batch_unshardable_events"] == 0
    assert snapshot["last_batch_projection_records"] == 1
    assert snapshot["last_batch_stale_projection_records"] == 1

    summary = metrics.batch_summary()
    assert summary["extracted_events"] == 3
    assert summary["owned_events"] == 2
    assert summary["unowned_events"] == 1
    assert summary["unshardable_events"] == 0
    assert summary["projection_records"] == 1
    assert summary["stale_projection_records"] == 1
    assert summary["frame_projection_records"] == 0
    assert summary["frame_stale_projection_records"] == 0
    assert summary["owned_ratio"] == 2 / 3
    assert summary["unowned_ratio"] == 1 / 3
    assert summary["unshardable_ratio"] == 0
    assert summary["projection_record_ratio"] == 0.5
    assert summary["stale_projection_ratio"] == 1.0
    assert summary["frame_projection_record_ratio"] == 0
    assert summary["frame_stale_projection_ratio"] == 0


def test_projector_metrics_render_includes_ipc_counters():
    """Prometheus export pulls IPC Tier 1.5 stats from the default store."""
    from noetl.core.projector.metrics import ProjectorMetrics, render_projector_metrics

    metrics = ProjectorMetrics()
    body = render_projector_metrics(metrics)
    # All seven counters appear in the body (values may be zero on a
    # fresh process — assertion is on the metric name being exported).
    assert "noetl_ipc_admit_attempts_total" in body
    assert "noetl_ipc_admit_success_total" in body
    assert "noetl_ipc_admit_failures_total" in body
    assert "noetl_ipc_read_attempts_total" in body
    assert "noetl_ipc_read_hits_total" in body
    assert "noetl_ipc_read_misses_total" in body
    assert "noetl_ipc_fallback_reads_total" in body
    assert "# HELP noetl_ipc_read_hits_total" in body


def test_projector_metrics_summary_includes_ipc_block():
    """summary()['ipc'] always present with zero-value counters."""
    from noetl.core.projector.metrics import ProjectorMetrics

    metrics = ProjectorMetrics()
    summary = metrics.summary()
    assert "ipc" in summary
    ipc = summary["ipc"]
    for key in [
        "admit_attempts",
        "admit_success",
        "admit_failures",
        "read_attempts",
        "read_hits",
        "read_misses",
        "fallback_reads",
        "admit_success_ratio",
        "read_hit_ratio",
        "fallback_ratio",
    ]:
        assert key in ipc, f"missing ipc.{key}"


def test_projector_metrics_summary_ipc_ratios_when_default_store_active(monkeypatch):
    """When TempStore tracks IPC activity, summary ratios reflect it."""
    from noetl.core.projector.metrics import ProjectorMetrics
    from noetl.core.storage import default_store

    snapshot = {
        "admit_attempts": 5,
        "admit_success": 4,
        "admit_failures": 1,
        "read_attempts": 10,
        "read_hits": 7,
        "read_misses": 3,
        "fallback_reads": 2,
    }
    monkeypatch.setattr(default_store, "_ipc_stats", dict(snapshot))

    metrics = ProjectorMetrics()
    ipc = metrics.summary()["ipc"]
    assert ipc["admit_success_ratio"] == 4 / 5
    assert ipc["read_hit_ratio"] == 0.7
    # fallback_ratio = fallback_reads / (read_attempts + fallback_reads)
    assert ipc["fallback_ratio"] == 2 / 12


def test_default_ipc_stats_returns_independent_snapshot():
    """default_ipc_stats() returns a copy — mutating it doesn't leak back."""
    from noetl.core.storage import default_ipc_stats, default_store

    first = default_ipc_stats()
    first["read_hits"] = 99999  # mutate the returned dict
    second = default_ipc_stats()
    # default_store's internal counter wasn't affected
    assert second["read_hits"] != 99999
    assert second["read_hits"] == default_store.ipc_stats()["read_hits"]


def test_projector_metrics_record_notification_tracks_frame_counters():
    """Frame-specific counters increment when record_notification is called with them."""
    from noetl.core.projector.metrics import ProjectorMetrics, render_projector_metrics

    metrics = ProjectorMetrics()
    metrics.record_notification(
        extracted_events=5,
        owned_events=4,
        projection_records=1,
        stale_projection_records=0,
        frame_projection_records=3,
        frame_stale_projection_records=1,
    )

    snapshot = metrics.snapshot()
    assert snapshot["frame_projection_records_total"] == 3
    assert snapshot["frame_projection_stale_records_total"] == 1
    assert snapshot["last_batch_frame_projection_records"] == 3
    assert snapshot["last_batch_frame_stale_projection_records"] == 1

    body = render_projector_metrics(metrics)
    assert "noetl_projector_frame_projection_records_total 3.0" in body
    assert "noetl_projector_frame_projection_stale_records_total 1.0" in body
    assert "noetl_projector_last_batch_frame_projection_records 3.0" in body
    assert "noetl_projector_last_batch_frame_stale_projection_records 1.0" in body

    summary = metrics.batch_summary()
    assert summary["frame_projection_records"] == 3
    assert summary["frame_stale_projection_records"] == 1
    assert summary["frame_projection_record_ratio"] == 0.75
    assert summary["frame_stale_projection_ratio"] == 1 / 3


def test_projector_metrics_batch_summary_handles_empty_batches():
    from noetl.core.projector.metrics import ProjectorMetrics

    metrics = ProjectorMetrics()

    summary = metrics.batch_summary()
    assert summary["extracted_events"] == 0
    assert summary["owned_events"] == 0
    assert summary["projection_records"] == 0
    assert summary["owned_ratio"] == 0
    assert summary["projection_record_ratio"] == 0
    assert summary["stale_projection_ratio"] == 0


def test_projector_metrics_record_message_actions():
    from noetl.core.projector.metrics import ProjectorMetrics, render_projector_metrics

    metrics = ProjectorMetrics()
    metrics.record_message_action("ack", None)
    metrics.record_message_action("nak", None)
    metrics.record_message_action("nak", 2.5)
    metrics.record_message_action("term", None)

    snapshot = metrics.snapshot()
    assert snapshot["acknowledged_notifications_total"] == 1
    assert snapshot["redelivery_requests_total"] == 2
    assert snapshot["delayed_redelivery_requests_total"] == 1
    assert snapshot["terminated_notifications_total"] == 1
    assert snapshot["last_action_unixtime"] > 0
    assert snapshot["last_ack_unixtime"] > 0
    assert snapshot["last_redelivery_request_unixtime"] > 0
    assert snapshot["last_termination_unixtime"] > 0
    assert snapshot["last_redelivery_delay_seconds"] == 2.5

    body = render_projector_metrics(metrics)
    assert "noetl_projector_acknowledged_notifications_total 1.0" in body
    assert "noetl_projector_redelivery_requests_total 2.0" in body
    assert "noetl_projector_delayed_redelivery_requests_total 1.0" in body
    assert "noetl_projector_terminated_notifications_total 1.0" in body
    assert "noetl_projector_last_redelivery_delay_seconds 2.5" in body

    summary = metrics.action_summary()
    assert summary["actions_total"] == 4
    assert summary["ack_ratio"] == 0.25
    assert summary["redelivery_ratio"] == 0.5
    assert summary["termination_ratio"] == 0.25


def test_projector_metrics_record_projection_errors():
    from noetl.core.projector.metrics import ProjectorMetrics, render_projector_metrics

    metrics = ProjectorMetrics()
    metrics.record_error()

    snapshot = metrics.snapshot()
    assert snapshot["errors_total"] == 1
    assert snapshot["projection_errors_total"] == 1
    assert snapshot["last_error_unixtime"] > 0

    body = render_projector_metrics(metrics)
    assert "noetl_projector_errors_total 1.0" in body
    assert "noetl_projector_projection_errors_total 1.0" in body

    summary = metrics.error_summary()
    assert summary["errors_total"] == 1
    assert summary["projection_errors_total"] == 1
    assert summary["decode_errors_total"] == 0
    assert summary["projection_error_ratio"] == 1.0
    assert summary["decode_error_ratio"] == 0
    assert summary["last_error_unixtime"] > 0


def test_projector_metrics_record_decode_errors():
    from noetl.core.projector.metrics import ProjectorMetrics, render_projector_metrics

    metrics = ProjectorMetrics()
    metrics.record_decode_error()

    snapshot = metrics.snapshot()
    assert snapshot["errors_total"] == 1
    assert snapshot["decode_errors_total"] == 1
    assert snapshot["projection_errors_total"] == 0
    assert snapshot["last_error_unixtime"] > 0

    body = render_projector_metrics(metrics)
    assert "noetl_projector_errors_total 1.0" in body
    assert "noetl_projector_decode_errors_total 1.0" in body

    summary = metrics.error_summary()
    assert summary["errors_total"] == 1
    assert summary["decode_errors_total"] == 1
    assert summary["projection_errors_total"] == 0
    assert summary["decode_error_ratio"] == 1.0
    assert summary["projection_error_ratio"] == 0
    assert summary["last_error_unixtime"] > 0


def test_projector_metrics_error_summary_handles_no_errors():
    from noetl.core.projector.metrics import ProjectorMetrics

    metrics = ProjectorMetrics()

    summary = metrics.error_summary()
    assert summary["errors_total"] == 0
    assert summary["decode_errors_total"] == 0
    assert summary["projection_errors_total"] == 0
    assert summary["decode_error_ratio"] == 0
    assert summary["projection_error_ratio"] == 0
    assert summary["last_error_unixtime"] == 0


def test_projector_metrics_export_projection_checkpoint_gauges():
    from noetl.core.projector.metrics import ProjectorMetrics, render_projector_metrics

    metrics = ProjectorMetrics()
    metrics.record_projection_checkpoints(
        [
            SimpleNamespace(
                source_event_id=31,
                meta={
                    "event_time_watermark": "2026-05-18T17:00:00Z",
                    "projected_at": "2026-05-18T17:00:02Z",
                    "projection_lag_ms": 2000,
                },
            )
        ]
    )

    snapshot = metrics.snapshot()
    assert snapshot["last_projection_source_event_id"] == 31
    assert snapshot["last_projection_lag_milliseconds"] == 2000
    assert snapshot["max_projection_lag_milliseconds"] == 2000

    body = render_projector_metrics(metrics)
    assert "noetl_projector_last_projection_source_event_id 31.0" in body
    assert "noetl_projector_last_projection_lag_milliseconds 2000.0" in body
    assert "noetl_projector_max_projection_lag_milliseconds 2000.0" in body


def test_projector_metrics_summary_combines_current_runtime_state():
    from noetl.core.projector.metrics import ProjectorMetrics

    metrics = ProjectorMetrics()
    metrics.record_notification(
        extracted_events=4,
        owned_events=3,
        unowned_events=1,
        projection_records=2,
        stale_projection_records=1,
    )
    metrics.record_message_action("ack", None)
    metrics.record_decode_error()
    metrics.record_projection_checkpoints(
        [
            SimpleNamespace(
                source_event_id=41,
                meta={
                    "event_time_watermark": "2026-05-18T18:00:00Z",
                    "projected_at": "2026-05-18T18:00:01Z",
                    "projection_lag_ms": 1000,
                },
            )
        ]
    )

    summary = metrics.summary()
    assert summary["notifications_total"] == 1
    assert summary["last_success_unixtime"] > 0
    assert summary["last_error_unixtime"] > 0
    assert summary["last_projection_source_event_id"] == 41
    assert summary["last_projection_lag_milliseconds"] == 1000
    assert summary["max_projection_lag_milliseconds"] == 1000
    assert summary["actions"]["actions_total"] == 1
    assert summary["actions"]["ack_ratio"] == 1.0
    assert summary["batch"]["owned_events"] == 3
    assert summary["batch"]["owned_ratio"] == 0.75
    assert summary["batch"]["stale_projection_ratio"] == 0.5
    assert summary["errors"]["errors_total"] == 1
    assert summary["errors"]["decode_error_ratio"] == 1.0


def test_projector_metrics_summary_payload_filters_labels():
    from noetl.core.projector.metrics import ProjectorMetrics, projector_metrics_summary

    metrics = ProjectorMetrics()
    metrics.record_notification(extracted_events=2, owned_events=1, projection_records=1)
    metrics.record_message_action("ack", None)

    payload = projector_metrics_summary(
        metrics,
        labels={
            "shard_id": "noetl-projector-0",
            "shard_index": "0",
            "empty": "",
        },
    )

    assert payload["labels"] == {
        "shard_id": "noetl-projector-0",
        "shard_index": "0",
    }
    assert payload["summary"]["notifications_total"] == 1
    assert payload["summary"]["actions"]["ack_ratio"] == 1.0
    assert payload["summary"]["batch"]["owned_ratio"] == 0.5


def test_projector_metrics_server_exposes_metrics_and_health():
    from noetl.core.projector.metrics import ProjectorMetrics, start_projector_metrics_server

    metrics = ProjectorMetrics()
    metrics.record_notification(extracted_events=1, owned_events=0, projection_records=0)
    server = start_projector_metrics_server(
        metrics,
        host="127.0.0.1",
        port=0,
        labels={"shard_id": "test-shard"},
    )
    host, port = server.server_address
    try:
        with urlopen(f"http://{host}:{port}/health", timeout=2) as response:
            assert response.read() == b"ok\n"
        with urlopen(f"http://{host}:{port}/summary", timeout=2) as response:
            summary = json.loads(response.read().decode("utf-8"))
        with urlopen(f"http://{host}:{port}/metrics", timeout=2) as response:
            body = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()

    assert summary["labels"] == {"shard_id": "test-shard"}
    assert summary["summary"]["notifications_total"] == 1
    assert summary["summary"]["batch"]["owned_events"] == 0
    assert "noetl_projector_empty_or_unowned_notifications_total" in body
    assert 'shard_id="test-shard"' in body
