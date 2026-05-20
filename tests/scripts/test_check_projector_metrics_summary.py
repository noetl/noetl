import json
from pathlib import Path

from scripts.check_projector_metrics_summary import main


def _summary_payload():
    return {
        "labels": {
            "shard_id": "noetl-projector-0",
            "shard_index": "0",
            "shard_count": "2",
        },
        "summary": {
            "notifications_total": 2.0,
            "last_success_unixtime": 1779312000.0,
            "last_error_unixtime": 0.0,
            "last_projection_source_event_id": 41.0,
            "last_projection_event_time_watermark_unixtime": 1779311999.0,
            "last_projection_projected_at_unixtime": 1779312000.0,
            "last_projection_lag_milliseconds": 1000.0,
            "max_projection_lag_milliseconds": 1000.0,
            "actions": {
                "actions_total": 2.0,
                "acknowledged_notifications_total": 1.0,
                "redelivery_requests_total": 1.0,
                "delayed_redelivery_requests_total": 0.0,
                "terminated_notifications_total": 0.0,
                "ack_ratio": 0.5,
                "redelivery_ratio": 0.5,
                "termination_ratio": 0.0,
            },
            "batch": {
                "extracted_events": 3.0,
                "owned_events": 2.0,
                "unowned_events": 1.0,
                "unshardable_events": 0.0,
                "projection_records": 2.0,
                "stale_projection_records": 0.0,
                "owned_ratio": 2 / 3,
                "unowned_ratio": 1 / 3,
                "unshardable_ratio": 0.0,
                "projection_record_ratio": 1.0,
                "stale_projection_ratio": 0.0,
            },
            "errors": {
                "errors_total": 0.0,
                "decode_errors_total": 0.0,
                "projection_errors_total": 0.0,
                "decode_error_ratio": 0.0,
                "projection_error_ratio": 0.0,
                "last_error_unixtime": 0.0,
            },
        },
    }


def _write_payload(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "projector-summary.json"
    path.write_text(json.dumps(payload))
    return path


def test_check_projector_metrics_summary_accepts_valid_payload(tmp_path: Path, capsys):
    path = _write_payload(tmp_path, _summary_payload())

    assert main(["--report", str(path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is True


def test_check_projector_metrics_summary_rejects_missing_required_field(
    tmp_path: Path,
    capsys,
):
    payload = _summary_payload()
    payload["summary"]["batch"].pop("owned_ratio")
    path = _write_payload(tmp_path, payload)

    assert main(["--report", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
    fields = {failure["field"] for failure in output["failures"]}
    assert "summary.batch.owned_ratio" in fields


def test_check_projector_metrics_summary_rejects_invalid_ratio(tmp_path: Path, capsys):
    payload = _summary_payload()
    payload["summary"]["actions"]["ack_ratio"] = 1.5
    path = _write_payload(tmp_path, payload)

    assert main(["--report", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
    fields = {failure["field"] for failure in output["failures"]}
    assert "summary.actions.ack_ratio" in fields


def test_check_projector_metrics_summary_rejects_invalid_label_value(
    tmp_path: Path,
    capsys,
):
    payload = _summary_payload()
    payload["labels"]["shard_id"] = ""
    path = _write_payload(tmp_path, payload)

    assert main(["--report", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
    fields = {failure["field"] for failure in output["failures"]}
    assert "labels.shard_id" in fields
