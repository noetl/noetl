import json
from pathlib import Path

from noetl.server.api.replay import replay_payload_resolution_summary
from scripts.check_replay_payload_resolution_report import main


def test_check_replay_payload_resolution_report_accepts_all_resolved(tmp_path: Path, capsys):
    rows = [
        {
            "scope": "frame",
            "resolution": {
                "ref": "noetl://payload/1",
                "resolved": True,
                "checksum": "a" * 64,
            },
        }
    ]
    report_path = tmp_path / "replay.json"
    report_path.write_text(
        json.dumps(
            {
                "payload_resolution": rows,
                "payload_resolution_summary": replay_payload_resolution_summary(rows),
            }
        )
    )

    assert main(["--report", str(report_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["matched"] is True
    assert report["summary"]["all_resolved"] is True


def test_check_replay_payload_resolution_report_rejects_unresolved(tmp_path: Path, capsys):
    rows = [
        {
            "scope": "frame",
            "resolution": {
                "ref": "noetl://payload/1",
                "resolved": False,
                "error": "missing",
            },
        }
    ]
    report_path = tmp_path / "replay.json"
    report_path.write_text(json.dumps({"payload_resolution": rows}))

    assert main(["--report", str(report_path)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["matched"] is False
    assert report["summary"]["unresolved"] == 1


def test_check_replay_payload_resolution_report_rejects_summary_mismatch(tmp_path: Path, capsys):
    rows = [
        {
            "scope": "frame",
            "resolution": {
                "ref": "noetl://payload/1",
                "resolved": True,
                "checksum": "a" * 64,
            },
        }
    ]
    report_path = tmp_path / "replay.json"
    report_path.write_text(
        json.dumps(
            {
                "payload_resolution": rows,
                "payload_resolution_summary": {
                    **replay_payload_resolution_summary(rows),
                    "checksum": "0" * 64,
                },
            }
        )
    )

    assert main(["--report", str(report_path)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["matched"] is False
    assert report["reason"] == "payload_resolution_summary checksum mismatch"


def test_check_replay_payload_resolution_report_rejects_summary_shape_mismatch(
    tmp_path: Path,
    capsys,
):
    rows = [
        {
            "scope": "frame",
            "resolution": {
                "ref": "noetl://payload/1",
                "resolved": True,
                "checksum": "a" * 64,
            },
        }
    ]
    report_path = tmp_path / "replay.json"
    report_path.write_text(
        json.dumps(
            {
                "payload_resolution": rows,
                "payload_resolution_summary": {
                    "total": "1",
                    "resolved": 1,
                    "unresolved": 0,
                    "unique_refs": 1,
                    "all_resolved": "true",
                    "checksum": "not-a-digest",
                    "extra": "field",
                },
            }
        )
    )

    assert main(["--report", str(report_path)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["matched"] is False
    assert report["reason"] == "payload_resolution_summary shape mismatch"
    fields = {failure["field"] for failure in report["summary_shape_failures"]}
    assert {
        "payload_resolution_summary.total",
        "payload_resolution_summary.all_resolved",
        "payload_resolution_summary.checksum",
        "payload_resolution_summary.extra",
    } <= fields


def test_check_replay_payload_resolution_report_rejects_non_object_summary(
    tmp_path: Path,
    capsys,
):
    rows = [
        {
            "scope": "frame",
            "resolution": {
                "ref": "noetl://payload/1",
                "resolved": True,
                "checksum": "a" * 64,
            },
        }
    ]
    report_path = tmp_path / "replay.json"
    report_path.write_text(
        json.dumps({"payload_resolution": rows, "payload_resolution_summary": "not-an-object"})
    )

    assert main(["--report", str(report_path)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["matched"] is False
    assert report["summary_shape_failures"][0]["field"] == "payload_resolution_summary"


def test_check_replay_payload_resolution_report_rejects_invalid_checksum_shape(
    tmp_path: Path,
    capsys,
):
    rows = [
        {
            "scope": "frame",
            "resolution": {
                "ref": "noetl://payload/1",
                "resolved": True,
                "checksum": "not-a-digest",
            },
        }
    ]
    report_path = tmp_path / "replay.json"
    report_path.write_text(json.dumps({"payload_resolution": rows}))

    assert main(["--report", str(report_path)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["matched"] is False
    assert report["reason"] == "payload checksum shape mismatch"
    assert report["checksum_shape_failures"][0]["ref"] == "noetl://payload/1"


def test_check_replay_payload_resolution_report_rejects_non_object_rows(
    tmp_path: Path,
    capsys,
):
    report_path = tmp_path / "replay.json"
    report_path.write_text(json.dumps({"payload_resolution": ["not-a-row"]}))

    assert main(["--report", str(report_path)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["matched"] is False
    assert report["reason"] == "payload_resolution row shape mismatch"
    assert report["row_shape_failures"][0]["index"] == 0


def test_check_replay_payload_resolution_report_rejects_non_object_resolution(
    tmp_path: Path,
    capsys,
):
    report_path = tmp_path / "replay.json"
    report_path.write_text(
        json.dumps({"payload_resolution": [{"scope": "frame", "resolution": "not-an-object"}]})
    )

    assert main(["--report", str(report_path)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["matched"] is False
    assert report["reason"] == "payload_resolution row shape mismatch"
    assert report["row_shape_failures"][0]["scope"] == "frame"
