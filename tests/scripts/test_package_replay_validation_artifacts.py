import json
import os
from pathlib import Path

from scripts.package_replay_validation_artifacts import main


def _manifest(tmp_path: Path) -> Path:
    replay = tmp_path / "replay.json"
    replay.write_text("{}")
    live_rows = tmp_path / "live-rows.json"
    live_rows.write_text("{}")
    live_checksums = tmp_path / "live-checksums.json"
    live_checksums.write_text("{}")
    manifest = tmp_path / "validation.json"
    manifest.write_text(
        json.dumps(
            {
                "matched": True,
                "artifacts": {
                    "replay": str(replay),
                    "live_rows": str(live_rows),
                    "live_checksums": str(live_checksums),
                    "report": str(manifest),
                },
            }
        )
    )
    return manifest


def test_package_replay_validation_artifacts_builds_and_checks_index(tmp_path: Path, capsys):
    manifest = _manifest(tmp_path)
    output = tmp_path / "artifact-index.json"

    assert main(["--manifest", str(manifest), "--output", str(output)]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["matched"] is True
    assert created["output"] == str(output)

    index = json.loads(output.read_text())
    assert index["path_base"] == "artifact_index_dir"
    assert index["manifest"] == "validation.json"
    roles = {entry["role"] for entry in index["artifacts"]}
    assert {"manifest", "replay", "live_rows", "live_checksums", "report"} <= roles
    assert all(entry["exists"] for entry in index["artifacts"])
    assert all(not Path(entry["path"]).is_absolute() for entry in index["artifacts"])

    assert main(["--check", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["matched"] is True


def test_package_replay_validation_artifacts_checks_relative_paths_from_index_dir(
    tmp_path: Path,
    capsys,
):
    manifest = _manifest(tmp_path)
    output = tmp_path / "artifact-index.json"
    assert main(["--manifest", str(manifest), "--output", str(output)]) == 0
    capsys.readouterr()

    previous_cwd = Path.cwd()
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    try:
        os.chdir(other_dir)
        assert main(["--check", str(output)]) == 0
    finally:
        os.chdir(previous_cwd)
    assert json.loads(capsys.readouterr().out)["matched"] is True


def test_package_replay_validation_artifacts_keeps_external_paths_absolute(
    tmp_path: Path,
    capsys,
):
    manifest = _manifest(tmp_path)
    external_dir = tmp_path.parent / f"{tmp_path.name}-external"
    external_dir.mkdir()
    external = external_dir / "extra.json"
    external.write_text("{}")
    output = tmp_path / "artifact-index.json"

    assert (
        main(
            [
                "--manifest",
                str(manifest),
                "--output",
                str(output),
                "--artifact",
                f"extra={external}",
            ]
        )
        == 0
    )
    index = json.loads(output.read_text())
    extra = next(entry for entry in index["artifacts"] if entry["role"] == "extra")
    assert extra["path"] == str(external)
    capsys.readouterr()
    assert main(["--check", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["matched"] is True


def test_package_replay_validation_artifacts_rejects_digest_drift(tmp_path: Path, capsys):
    manifest = _manifest(tmp_path)
    output = tmp_path / "artifact-index.json"
    assert main(["--manifest", str(manifest), "--output", str(output)]) == 0
    capsys.readouterr()

    (tmp_path / "replay.json").write_text('{"changed":true}')
    assert main(["--check", str(output)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert any(failure["reason"] == "sha256 drift" for failure in result["failures"])


def test_package_replay_validation_artifacts_rejects_missing_required_role(
    tmp_path: Path,
    capsys,
):
    manifest = tmp_path / "validation.json"
    manifest.write_text("{}")
    output = tmp_path / "artifact-index.json"
    output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-05-20T00:00:00Z",
                "path_base": "artifact_index_dir",
                "manifest": "validation.json",
                "artifacts": [],
            }
        )
    )

    assert main(["--check", str(output)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert any(failure.get("role") == "manifest" for failure in result["failures"])


def test_package_replay_validation_artifacts_rejects_missing_manifest_pointer(
    tmp_path: Path,
    capsys,
):
    output = tmp_path / "artifact-index.json"
    output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-05-20T00:00:00Z",
                "path_base": "artifact_index_dir",
                "manifest": "missing-validation.json",
                "artifacts": [],
            }
        )
    )

    assert main(["--check", str(output)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert any(failure["field"] == "manifest" for failure in result["failures"])


def test_package_replay_validation_artifacts_rejects_unknown_path_base(
    tmp_path: Path,
    capsys,
):
    manifest = tmp_path / "validation.json"
    manifest.write_text("{}")
    output = tmp_path / "artifact-index.json"
    output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-05-20T00:00:00Z",
                "path_base": "cwd",
                "manifest": "validation.json",
                "artifacts": [],
            }
        )
    )

    assert main(["--check", str(output)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert any(failure["field"] == "path_base" for failure in result["failures"])


def test_package_replay_validation_artifacts_rejects_duplicate_roles(tmp_path: Path, capsys):
    manifest = _manifest(tmp_path)
    output = tmp_path / "artifact-index.json"
    assert main(["--manifest", str(manifest), "--output", str(output)]) == 0
    index = json.loads(output.read_text())
    index["artifacts"].append(dict(index["artifacts"][0]))
    output.write_text(json.dumps(index))
    capsys.readouterr()

    assert main(["--check", str(output)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert any(failure["reason"] == "duplicate artifact role" for failure in result["failures"])


def test_package_replay_validation_artifacts_rejects_unpaired_live_roles(
    tmp_path: Path,
    capsys,
):
    manifest = _manifest(tmp_path)
    output = tmp_path / "artifact-index.json"
    assert main(["--manifest", str(manifest), "--output", str(output)]) == 0
    index = json.loads(output.read_text())
    index["artifacts"] = [
        entry for entry in index["artifacts"] if entry["role"] != "live_checksums"
    ]
    output.write_text(json.dumps(index))
    capsys.readouterr()

    assert main(["--check", str(output)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert any("paired artifact roles" in failure["reason"] for failure in result["failures"])
