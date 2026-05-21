import json

from scripts import render_projector_phase2_command


def test_render_projector_phase2_command_outputs_shell(capsys, tmp_path):
    assert (
        render_projector_phase2_command.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--output-dir",
                str(tmp_path),
                "--projector-summary-url",
                "projector-0=http://projector-0.example:9090",
                "--live-rows",
                str(tmp_path / "live-rows.json"),
                "--require-projection-parity",
                "--report-output",
                str(tmp_path / "phase2-report.json"),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "scripts/run_projector_phase2_validation.py" in output
    assert "--projector-summary-url projector-0=http://projector-0.example:9090" in output
    assert "--limit 100000" in output
    assert "--timeout 60.0" in output
    assert "--live-rows" in output
    assert "--require-projection-parity" in output
    assert "--report-output" in output


def test_render_projector_phase2_command_outputs_json_with_runtime_options(capsys, tmp_path):
    assert (
        render_projector_phase2_command.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--output-dir",
                str(tmp_path),
                "--limit",
                "25",
                "--timeout",
                "12.5",
                "--resolve-payloads",
                "--export-live-rows-postgres",
                "--postgres-dsn",
                "postgresql://user@localhost/noetl",
                "--projector-summary",
                str(tmp_path / "projector-summary.json"),
                "--report-output",
                str(tmp_path / "phase2-report.json"),
                "--json",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["argv"][1] == "scripts/run_projector_phase2_validation.py"
    assert "--projector-summary" in output["argv"]
    assert output["argv"][output["argv"].index("--limit") + 1] == "25"
    assert output["argv"][output["argv"].index("--timeout") + 1] == "12.5"
    assert "--resolve-payloads" in output["argv"]
    assert "--export-live-rows-postgres" in output["argv"]
    assert output["argv"][output["argv"].index("--postgres-dsn") + 1] == "postgresql://user@localhost/noetl"
    assert output["argv"][output["argv"].index("--report-output") + 1].endswith("phase2-report.json")
    assert "scripts/run_projector_phase2_validation.py" in output["shell"]


def test_render_projector_phase2_command_requires_projector_source(tmp_path):
    try:
        render_projector_phase2_command.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--output-dir",
                str(tmp_path),
            ]
        )
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parser error")


def test_render_projector_phase2_command_rejects_multiple_live_inputs(tmp_path):
    try:
        render_projector_phase2_command.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--output-dir",
                str(tmp_path),
                "--projector-summary",
                str(tmp_path / "projector-summary.json"),
                "--live-rows",
                str(tmp_path / "live-rows.json"),
                "--live-checksums",
                str(tmp_path / "live-checksums.json"),
            ]
        )
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parser error")


def test_render_projector_phase2_command_rejects_postgres_dsn_without_export(tmp_path):
    try:
        render_projector_phase2_command.main(
            [
                "--base-url",
                "http://noetl.example",
                "--execution-id",
                "123",
                "--output-dir",
                str(tmp_path),
                "--projector-summary",
                str(tmp_path / "projector-summary.json"),
                "--postgres-dsn",
                "postgresql://user@localhost/noetl",
            ]
        )
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected parser error")
