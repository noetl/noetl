import json
from pathlib import Path

from scripts.check_worker_ipc_metrics import main


def _metrics_body() -> str:
    labels = '{node_id="node-a",runtime="cpu",worker_id="worker-a",worker_pool="default"}'
    return "\n".join(
        [
            f"noetl_storage_ipc_admit_attempts_total{labels} 2",
            f"noetl_storage_ipc_admit_success_total{labels} 1",
            f"noetl_storage_ipc_admit_failures_total{labels} 0",
            f"noetl_storage_ipc_read_attempts_total{labels} 2",
            f"noetl_storage_ipc_read_hits_total{labels} 1",
            f"noetl_storage_ipc_read_misses_total{labels} 1",
            f"noetl_storage_ipc_fallback_reads_total{labels} 1",
            f"noetl_storage_ipc_read_hit_ratio{labels} 0.5",
            "",
        ]
    )


def test_check_worker_ipc_metrics_accepts_phase3_activity(tmp_path: Path, capsys):
    path = tmp_path / "worker.prom"
    path.write_text(_metrics_body())

    assert main(["--metrics", str(path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is True


def test_check_worker_ipc_metrics_rejects_missing_activity(tmp_path: Path, capsys):
    path = tmp_path / "worker.prom"
    path.write_text(_metrics_body().replace("noetl_storage_ipc_read_hits_total", "missing_metric"))

    assert main(["--metrics", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
    assert any(failure["field"] == "noetl_storage_ipc_read_hits_total" for failure in output["failures"])


def test_check_worker_ipc_metrics_accepts_admission_only_activity(tmp_path: Path, capsys):
    path = tmp_path / "worker.prom"
    body = (
        _metrics_body()
        .replace("noetl_storage_ipc_read_hits_total{node_id=\"node-a\",runtime=\"cpu\",worker_id=\"worker-a\",worker_pool=\"default\"} 1", "noetl_storage_ipc_read_hits_total{node_id=\"node-a\",runtime=\"cpu\",worker_id=\"worker-a\",worker_pool=\"default\"} 0")
        .replace("noetl_storage_ipc_fallback_reads_total{node_id=\"node-a\",runtime=\"cpu\",worker_id=\"worker-a\",worker_pool=\"default\"} 1", "noetl_storage_ipc_fallback_reads_total{node_id=\"node-a\",runtime=\"cpu\",worker_id=\"worker-a\",worker_pool=\"default\"} 0")
    )
    path.write_text(body)

    assert main(["--metrics", str(path), "--require-admission-only"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is True
