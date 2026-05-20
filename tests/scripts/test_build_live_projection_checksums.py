import json
from pathlib import Path

import pytest

from scripts import build_live_projection_checksums


def _rows():
    return {
        "execution": [
            {
                "execution_id": 123,
                "tenant_id": "tenant-a",
                "organization_id": "org-a",
                "status": "COMPLETED",
                "last_event_id": 2,
            }
        ],
        "stages": [],
        "frames": [],
        "commands": [],
        "business_objects": [],
        "loops": [],
    }


def test_build_live_projection_checksums_writes_bundle(tmp_path: Path, capsys):
    rows_path = tmp_path / "live-rows.json"
    output_path = tmp_path / "live-checksums.json"
    rows_path.write_text(json.dumps(_rows()))

    assert (
        build_live_projection_checksums.main(
            ["--rows", str(rows_path), "--output", str(output_path)]
        )
        == 0
    )

    output = json.loads(output_path.read_text())
    assert set(output["projection_checksums"]) == {
        "execution",
        "stages",
        "frames",
        "commands",
        "business_objects",
        "loops",
    }
    assert output["row_counts"]["execution"] == 1
    assert json.loads(capsys.readouterr().out)["output"] == str(output_path)


def test_build_live_projection_checksums_accepts_nested_rows(tmp_path: Path):
    rows_path = tmp_path / "live-rows.json"
    output_path = tmp_path / "live-checksums.json"
    rows_path.write_text(json.dumps({"rows": _rows()}))

    assert (
        build_live_projection_checksums.main(
            ["--rows", str(rows_path), "--output", str(output_path)]
        )
        == 0
    )


def test_build_live_projection_checksums_rejects_nested_row_count_drift(tmp_path: Path):
    rows_path = tmp_path / "live-rows.json"
    output_path = tmp_path / "live-checksums.json"
    rows_path.write_text(json.dumps({"rows": _rows(), "row_counts": {"execution": 2}}))

    with pytest.raises(ValueError, match="row_counts.execution"):
        build_live_projection_checksums.main(
            ["--rows", str(rows_path), "--output", str(output_path)]
        )


def test_build_live_projection_checksums_rejects_unknown_surface(tmp_path: Path):
    rows = {**_rows(), "extra": []}
    rows_path = tmp_path / "live-rows.json"
    rows_path.write_text(json.dumps(rows))

    with pytest.raises(ValueError, match="unknown live projection row surfaces"):
        build_live_projection_checksums.main(
            ["--rows", str(rows_path), "--output", str(tmp_path / "out.json")]
        )


def test_build_live_projection_checksums_rejects_non_object_rows(tmp_path: Path):
    rows = _rows()
    rows["frames"] = ["not-a-row"]
    rows_path = tmp_path / "live-rows.json"
    rows_path.write_text(json.dumps(rows))

    with pytest.raises(ValueError, match="frames rows must be objects"):
        build_live_projection_checksums.main(
            ["--rows", str(rows_path), "--output", str(tmp_path / "out.json")]
        )
