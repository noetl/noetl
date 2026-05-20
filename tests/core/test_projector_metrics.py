from __future__ import annotations

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
        labels={"shard_id": "noetl-projector-0", "consumer": "consumer-a"},
    )

    assert 'consumer="consumer-a"' in body
    assert 'shard_id="noetl-projector-0"' in body
    assert "noetl_projector_notifications_total" in body
    assert "noetl_projector_events_extracted_total" in body
    assert "noetl_projector_events_owned_total" in body
    assert "noetl_projector_events_unowned_total" in body
    assert "noetl_projector_events_unshardable_total" in body
    assert "noetl_projector_projection_records_total" in body
    assert "noetl_projector_projection_stale_records_total" in body
    assert " 1.0" in body


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
        with urlopen(f"http://{host}:{port}/metrics", timeout=2) as response:
            body = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()

    assert "noetl_projector_empty_or_unowned_notifications_total" in body
    assert 'shard_id="test-shard"' in body
