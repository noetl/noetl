import json
from pathlib import Path

from scripts import fetch_projector_metrics_summary


class _Response:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self._body


def test_fetch_projector_metrics_summary_appends_summary_path(monkeypatch):
    seen = []

    def _urlopen(url, timeout):
        seen.append((url, timeout))
        return _Response(b'{"labels":{},"summary":{"notifications_total":1}}')

    monkeypatch.setattr(fetch_projector_metrics_summary, "urlopen", _urlopen)

    payload = fetch_projector_metrics_summary.fetch_projector_metrics_summary(
        "http://127.0.0.1:9090",
        timeout=2.5,
    )

    assert payload["summary"]["notifications_total"] == 1
    assert seen == [("http://127.0.0.1:9090/summary", 2.5)]


def test_fetch_projector_metrics_summary_keeps_existing_summary_path(monkeypatch):
    seen = []

    def _urlopen(url, timeout):
        seen.append((url, timeout))
        return _Response(b'{"labels":{},"summary":{}}')

    monkeypatch.setattr(fetch_projector_metrics_summary, "urlopen", _urlopen)

    fetch_projector_metrics_summary.fetch_projector_metrics_summary(
        "http://projector.example/summary",
        timeout=1.0,
    )

    assert seen == [("http://projector.example/summary", 1.0)]


def test_fetch_projector_metrics_summary_writes_output(monkeypatch, tmp_path: Path, capsys):
    def _urlopen(_url, timeout):
        return _Response(b'{"labels":{"shard_id":"p0"},"summary":{"notifications_total":1}}')

    monkeypatch.setattr(fetch_projector_metrics_summary, "urlopen", _urlopen)
    output_path = tmp_path / "summary.json"

    assert (
        fetch_projector_metrics_summary.main(
            [
                "--url",
                "http://projector.example",
                "--output",
                str(output_path),
            ]
        )
        == 0
    )

    assert json.loads(output_path.read_text())["labels"]["shard_id"] == "p0"
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is True
    assert output["output"] == str(output_path)


def test_fetch_projector_metrics_summary_rejects_relative_url(capsys, tmp_path: Path):
    assert (
        fetch_projector_metrics_summary.main(
            [
                "--url",
                "localhost:9090",
                "--output",
                str(tmp_path / "summary.json"),
            ]
        )
        == 1
    )

    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
