import json
from pathlib import Path

from scripts.check_live_projection_rows import _canonical_checksum, main


def _artifact() -> dict:
    rows = {
        "execution": [{"execution_id": 123}],
        "stages": [],
        "frames": [],
        "commands": [],
        "business_objects": [],
        "loops": [],
    }
    return {
        "schema_version": 1,
        "adapter": "postgres",
        "execution_id": 123,
        "tenant_id": "tenant-a",
        "organization_id": "org-a",
        "projection": "all",
        "exported_at": "2026-05-20T00:00:00Z",
        "rows": rows,
        "row_counts": {surface: len(values) for surface, values in rows.items()},
        "rows_checksum": _canonical_checksum(rows),
    }


def test_check_live_projection_rows_accepts_valid_artifact(tmp_path: Path, capsys):
    path = tmp_path / "live-rows.json"
    path.write_text(json.dumps(_artifact()))

    assert main(["--rows", str(path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is True
    assert output["row_counts"]["execution"] == 1


def test_check_live_projection_rows_rejects_bad_row_count(tmp_path: Path, capsys):
    artifact = _artifact()
    artifact["row_counts"]["execution"] = 99
    path = tmp_path / "live-rows.json"
    path.write_text(json.dumps(artifact))

    assert main(["--rows", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert "row_counts.execution" in {failure["field"] for failure in output["failures"]}


def test_check_live_projection_rows_rejects_checksum_drift(tmp_path: Path, capsys):
    artifact = _artifact()
    artifact["rows"]["execution"].append({"execution_id": 124})
    path = tmp_path / "live-rows.json"
    path.write_text(json.dumps(artifact))

    assert main(["--rows", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert "rows_checksum" in {failure["field"] for failure in output["failures"]}
