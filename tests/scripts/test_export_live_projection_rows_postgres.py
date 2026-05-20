import json
from pathlib import Path

from scripts import export_live_projection_rows_postgres as exporter


def test_rows_from_projection_state_exports_business_objects_and_loops():
    business_rows, loop_rows = exporter._rows_from_projection_state(
        {
            "business_objects": {
                "patient/1": {
                    "object_type": "patient",
                    "object_id": "1",
                    "status": "active",
                }
            },
            "loops": {
                "loop-a": {
                    "step_name": "fetch",
                    "done": 10,
                    "failed": 0,
                    "completed": True,
                }
            },
        }
    )

    assert business_rows == [
        {
            "object_key": "patient/1",
            "object_type": "patient",
            "object_id": "1",
            "status": "active",
        }
    ]
    assert loop_rows == [
        {
            "loop_id": "loop-a",
            "step_name": "fetch",
            "done": 10,
            "failed": 0,
            "completed": True,
        }
    ]


def test_export_live_projection_rows_uses_plain_adapter_queries(monkeypatch):
    calls = []

    def _select_all(conn, sql, params):
        calls.append((sql, params))
        if sql is exporter.EXECUTION_SQL:
            return [{"execution_id": 123, "status": "COMPLETED", "event_count": 4}]
        if sql is exporter.STAGE_SQL:
            return [{"stage_id": 10, "status": "CLOSED", "frame_count": 1}]
        if sql is exporter.FRAME_SQL:
            return [{"frame_id": 20, "stage_id": 10, "status": "COMMITTED"}]
        if sql is exporter.COMMAND_SQL:
            return [
                {
                    "command_id": 30,
                    "stage_id": 10,
                    "frame_id": 20,
                    "status": "COMPLETED",
                }
            ]
        if sql is exporter.PROJECTION_SQL:
            return [
                {
                    "state": {
                        "business_objects": {
                            "patient/1": {"object_type": "patient", "object_id": "1"}
                        },
                        "loops": {
                            "loop-a": {
                                "step_name": "fetch",
                                "done": 1,
                                "completed": True,
                            }
                        },
                    }
                }
            ]
        raise AssertionError("unexpected query")

    monkeypatch.setattr(exporter, "_select_all", _select_all)

    rows = exporter.export_live_projection_rows(
        object(),
        execution_id=123,
        tenant_id="tenant-a",
        organization_id="org-a",
        projection="all",
    )

    assert set(rows) == set(exporter.SURFACES)
    assert rows["execution"][0]["execution_id"] == 123
    assert rows["business_objects"][0]["object_key"] == "patient/1"
    assert rows["loops"][0]["loop_id"] == "loop-a"
    assert calls[-1][1] == ("tenant-a", "org-a", "execution/123/all")


def test_main_writes_adapter_neutral_rows(monkeypatch, tmp_path: Path, capsys):
    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def _connect(dsn):
        assert dsn == "postgresql://example"
        return FakeConnection()

    def _export(conn, *, execution_id, tenant_id, organization_id, projection):
        assert execution_id == 123
        assert tenant_id == "tenant-a"
        assert organization_id == "org-a"
        assert projection == "all"
        return {surface: [] for surface in exporter.SURFACES}

    monkeypatch.setattr(exporter, "_connect", _connect)
    monkeypatch.setattr(exporter, "export_live_projection_rows", _export)

    output = tmp_path / "live-rows.json"
    assert (
        exporter.main(
            [
                "--execution-id",
                "123",
                "--tenant-id",
                "tenant-a",
                "--organization-id",
                "org-a",
                "--dsn",
                "postgresql://example",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    payload = json.loads(output.read_text())
    assert payload["adapter"] == "postgres"
    assert payload["rows"] == {surface: [] for surface in exporter.SURFACES}
    assert payload["row_counts"] == {surface: 0 for surface in exporter.SURFACES}
    assert json.loads(capsys.readouterr().out)["output"] == str(output)
