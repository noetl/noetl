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
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "scripts/run_projector_phase2_validation.py" in output
    assert "--projector-summary-url projector-0=http://projector-0.example:9090" in output
    assert "--live-rows" in output
    assert "--require-projection-parity" in output


def test_render_projector_phase2_command_outputs_json(capsys, tmp_path):
    assert (
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
                "--json",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["argv"][1] == "scripts/run_projector_phase2_validation.py"
    assert "--projector-summary" in output["argv"]
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
