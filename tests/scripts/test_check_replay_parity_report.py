import json
from pathlib import Path

from scripts.check_replay_parity_report import main


def test_check_replay_parity_report_accepts_matching_raw_bundles(tmp_path: Path, capsys):
    bundle = {
        "execution": "a" * 64,
        "stages": "b" * 64,
        "frames": "c" * 64,
        "commands": "d" * 64,
        "business_objects": "e" * 64,
        "loops": "f" * 64,
    }
    replayed_path = tmp_path / "replayed.json"
    live_path = tmp_path / "live.json"
    replayed_path.write_text(json.dumps(bundle))
    live_path.write_text(json.dumps(bundle))

    assert main(["--replayed", str(replayed_path), "--live", str(live_path)]) == 0
    assert json.loads(capsys.readouterr().out)["matched"] is True


def test_check_replay_parity_report_rejects_diverged_nested_bundles(tmp_path: Path, capsys):
    replayed = {
        "projection_checksums": {
            "execution": "a" * 64,
            "stages": "b" * 64,
            "frames": "c" * 64,
            "commands": "d" * 64,
            "business_objects": "e" * 64,
            "loops": "f" * 64,
        }
    }
    live = {
        "projection_checksums": {
            **replayed["projection_checksums"],
            "frames": "0" * 64,
        }
    }
    replayed_path = tmp_path / "replayed.json"
    live_path = tmp_path / "live.json"
    replayed_path.write_text(json.dumps(replayed))
    live_path.write_text(json.dumps(live))

    assert main(["--replayed", str(replayed_path), "--live", str(live_path)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["matched"] is False
    assert report["surfaces"]["frames"]["matched"] is False


def test_check_replay_parity_report_rejects_invalid_checksum_shape(tmp_path: Path, capsys):
    bundle = {
        "execution": "not-a-digest",
        "stages": "b" * 64,
        "frames": "c" * 64,
        "commands": "d" * 64,
        "business_objects": "e" * 64,
        "loops": "f" * 64,
    }
    replayed_path = tmp_path / "replayed.json"
    live_path = tmp_path / "live.json"
    replayed_path.write_text(json.dumps(bundle))
    live_path.write_text(json.dumps(bundle))

    assert main(["--replayed", str(replayed_path), "--live", str(live_path)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["matched"] is False
    assert report["checksum_shape_failures"][0]["surface"] == "execution"


def test_check_replay_parity_report_can_allow_legacy_checksum_shape(tmp_path: Path, capsys):
    bundle = {
        "execution": "legacy",
        "stages": "legacy",
        "frames": "legacy",
        "commands": "legacy",
        "business_objects": "legacy",
        "loops": "legacy",
    }
    replayed_path = tmp_path / "replayed.json"
    live_path = tmp_path / "live.json"
    replayed_path.write_text(json.dumps(bundle))
    live_path.write_text(json.dumps(bundle))

    assert (
        main(
            [
                "--replayed",
                str(replayed_path),
                "--live",
                str(live_path),
                "--allow-invalid-checksum-shape",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["matched"] is True


def test_check_replay_parity_report_rejects_missing_required_surface(tmp_path: Path, capsys):
    bundle = {
        "execution": "a" * 64,
        "stages": "b" * 64,
        "frames": "c" * 64,
        "commands": "d" * 64,
        "business_objects": "e" * 64,
    }
    replayed_path = tmp_path / "replayed.json"
    live_path = tmp_path / "live.json"
    replayed_path.write_text(json.dumps(bundle))
    live_path.write_text(json.dumps(bundle))

    assert main(["--replayed", str(replayed_path), "--live", str(live_path)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["matched"] is False
    assert report["surface_shape_failures"][0]["surface"] == "loops"


def test_check_replay_parity_report_rejects_unknown_surface(tmp_path: Path, capsys):
    bundle = {
        "execution": "a" * 64,
        "stages": "b" * 64,
        "frames": "c" * 64,
        "commands": "d" * 64,
        "business_objects": "e" * 64,
        "loops": "f" * 64,
        "extra": "0" * 64,
    }
    replayed_path = tmp_path / "replayed.json"
    live_path = tmp_path / "live.json"
    replayed_path.write_text(json.dumps(bundle))
    live_path.write_text(json.dumps(bundle))

    assert main(["--replayed", str(replayed_path), "--live", str(live_path)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["matched"] is False
    assert report["surface_shape_failures"][0]["surface"] == "extra"
