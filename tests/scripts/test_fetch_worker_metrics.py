from pathlib import Path

from scripts import fetch_worker_metrics


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return b"noetl_worker_up 1\n"


def test_fetch_worker_metrics_appends_metrics_path(monkeypatch, tmp_path: Path):
    seen: list[tuple[str, float]] = []

    def _urlopen(url: str, timeout: float):
        seen.append((url, timeout))
        return _Response()

    monkeypatch.setattr(fetch_worker_metrics, "urlopen", _urlopen)
    output = tmp_path / "worker.prom"

    assert fetch_worker_metrics.main(["--url", "http://worker.example", "--output", str(output), "--timeout", "1"]) == 0
    assert seen == [("http://worker.example/metrics", 1.0)]
    assert output.read_text() == "noetl_worker_up 1\n"
