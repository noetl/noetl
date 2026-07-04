import json
import sys
from pathlib import Path

from scripts.smoke_ehdb_local_reference_summary import REQUIRED_SUMMARY_FIELDS, main, run_smoke


def test_run_smoke_validates_summary_shape(tmp_path):
    log_path = tmp_path / "ehdb.jsonl"
    helper = _summary_helper(tmp_path)

    payload = run_smoke(
        helper_bin=str(helper),
        log_path=log_path,
        env={"PATH": "/usr/bin"},
    )

    assert payload["log_path"] == str(log_path)
    assert payload["transaction_count"] == 0
    assert set(REQUIRED_SUMMARY_FIELDS).issubset(payload)


def test_main_prints_summary_json(tmp_path, capsys):
    log_path = tmp_path / "ehdb.jsonl"
    helper = _summary_helper(tmp_path)

    result = main(["--helper-bin", str(helper), "--log", str(log_path)])

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["log_path"] == str(log_path)
    assert output["storage_replica_count"] == 0


def test_main_reports_missing_fields(tmp_path, capsys):
    helper = _helper_script(
        tmp_path,
        """
import json

print(json.dumps({"log_path": "missing-counts"}))
""",
    )

    result = main(["--helper-bin", str(helper), "--log", str(tmp_path / "ehdb.jsonl")])

    assert result == 1
    assert "missing required fields" in capsys.readouterr().err


def _summary_helper(tmp_path: Path) -> Path:
    fields = {field: 0 for field in REQUIRED_SUMMARY_FIELDS}
    return _helper_script(
        tmp_path,
        f"""
import json
import sys

payload = {fields!r}
payload["log_path"] = sys.argv[3]
print(json.dumps(payload))
""",
    )


def _helper_script(tmp_path: Path, body: str) -> Path:
    helper = tmp_path / "ehdb-local-reference"
    helper.write_text(f"#!{sys.executable}\n{body.lstrip()}", encoding="utf-8")
    helper.chmod(0o755)
    return helper
