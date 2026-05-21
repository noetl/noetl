import json
from pathlib import Path

from scripts.build_storage_phase5_report import build_storage_phase5_report, main
from scripts.check_storage_phase5_evidence import validate_storage_phase5_report


def test_build_storage_phase5_report_matches_current_repo():
    repo_root = Path(__file__).resolve().parents[2]

    report = build_storage_phase5_report(repo_root)
    result = validate_storage_phase5_report(report)

    assert result["matched"] is True
    assert report["direct_backend_construction"]["matched"] is True


def test_build_storage_phase5_report_cli_writes_report(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    output = tmp_path / "storage-phase5-report.json"

    assert main(["--repo-root", str(repo_root), "--output", str(output)]) == 0
    report = json.loads(output.read_text())

    assert validate_storage_phase5_report(report)["matched"] is True
