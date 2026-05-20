from __future__ import annotations

from urllib.request import urlopen


def test_worker_metrics_render_storage_ipc_labels(monkeypatch):
    from noetl.worker import metrics as worker_metrics

    monkeypatch.setattr(
        worker_metrics.default_store,
        "ipc_stats",
        lambda: {
            "admit_attempts": 2,
            "admit_success": 1,
            "admit_failures": 1,
            "read_attempts": 4,
            "read_hits": 3,
            "read_misses": 1,
            "fallback_reads": 1,
        },
    )

    body = worker_metrics.render_worker_metrics(
        worker_id='worker-"a"',
        labels={"worker_pool": "worker-cpu-01", "runtime": "cpu"},
    )

    assert 'worker_id="worker-\\"a\\""' in body
    assert 'worker_pool="worker-cpu-01"' in body
    assert 'runtime="cpu"' in body
    assert "noetl_storage_ipc_admit_attempts_total" in body
    assert "noetl_storage_ipc_read_hit_ratio" in body
    assert " 0.75" in body


def test_worker_metrics_server_exposes_metrics_and_health(monkeypatch):
    from noetl.worker import metrics as worker_metrics

    monkeypatch.setattr(
        worker_metrics.default_store,
        "ipc_stats",
        lambda: {
            "admit_attempts": 1,
            "admit_success": 1,
            "admit_failures": 0,
            "read_attempts": 0,
            "read_hits": 0,
            "read_misses": 0,
            "fallback_reads": 0,
        },
    )

    server = worker_metrics.start_worker_metrics_server(
        worker_id="worker-test",
        host="127.0.0.1",
        port=0,
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

    assert "noetl_worker_up" in body
    assert "noetl_storage_ipc_admit_success_total" in body
