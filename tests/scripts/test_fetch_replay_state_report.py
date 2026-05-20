import json
from pathlib import Path

import pytest

from scripts import fetch_replay_state_report


def test_fetch_replay_state_report_writes_response(monkeypatch, tmp_path: Path, capsys):
    captured = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"projection_checksums": {"execution": "a" * 64}}).encode()

    def _urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(fetch_replay_state_report, "urlopen", _urlopen)
    output_path = tmp_path / "reports" / "replay.json"

    assert (
        fetch_replay_state_report.main(
            [
                "--base-url",
                "http://noetl.example/",
                "--execution-id",
                "123",
                "--tenant-id",
                "tenant-a",
                "--organization-id",
                "org-a",
                "--resolve-payloads",
                "--output",
                str(output_path),
                "--timeout",
                "7",
            ]
        )
        == 0
    )

    assert output_path.exists()
    assert json.loads(output_path.read_text()) == {
        "projection_checksums": {"execution": "a" * 64}
    }
    assert "execution_id=123" in captured["url"]
    assert "tenant_id=tenant-a" in captured["url"]
    assert "organization_id=org-a" in captured["url"]
    assert "resolve_payloads=true" in captured["url"]
    assert captured["timeout"] == 7.0
    assert json.loads(capsys.readouterr().out)["output"] == str(output_path)


def test_fetch_replay_state_report_rejects_multiple_cutoffs(tmp_path: Path):
    with pytest.raises(SystemExit):
        fetch_replay_state_report.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--as-of-event-id",
                "1",
                "--as-of-position",
                "1",
                "--output",
                str(tmp_path / "replay.json"),
            ]
        )
